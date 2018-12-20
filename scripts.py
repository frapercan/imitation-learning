"""
Random experiments. As this file expands, I will probably move individual
experiments into an scripts/ directory.

These scripts are meant to be run in a Jupyter notebook (displays figures)
but also automatically save timestamped figures to the output/ directory.
"""
import datetime

from matplotlib import pyplot as plt
import tensorflow as tf
import tqdm

from yairl.airl import AIRLTrainer
from yairl.reward_net import BasicRewardNet
import yairl.util as util


def _init_trainer(env, use_expert_rollouts=True, n_rollout_samples=1000):
    """
    Initialize an AIRL trainer to train a BasicRewardNet (discriminator)
    versus a policy (generator).

    Params:
    use_expert_rollouts (bool) -- If True, then load an expert policy to
      generate training data, and error if this expert policy doesn't exist for
      this environment. If False, then generate random rollouts.

    Return:
    trainer (AIRLTrainer) -- The AIRL trainer.
    """
    if isinstance(env, str):
        env = util.make_vec_env(env, 32)
    else:
        env = util.maybe_load_env(env, True)
    policy = util.make_blank_policy(env, init_tensorboard=False)
    if use_expert_rollouts:
        rollout_policy = util.load_expert_policy(env)
        if rollout_policy is None:
            raise ValueError(env)
    else:
        rollout_policy = policy

    obs_old, act, obs_new, _ = util.rollout_generate(rollout_policy, env,
            n_timesteps=n_rollout_samples)

    rn = BasicRewardNet(env)
    trainer = AIRLTrainer(env, policy=policy, reward_net=rn,
            expert_obs_old=obs_old, expert_act=act, expert_obs_new=obs_new)
    return trainer


def plot_episode_reward_vs_time(env='CartPole-v1', n_episodes=50,
        n_epochs_per_plot=250, n_plots=100):
    """
    Make sure that generator policy trained to mimick expert policy
    demonstrations) achieves higher reward than a random policy.

    In other words, perform a basic check on the imitation learning
    capabilities of AIRLTrainer.
    """
    trainer = _init_trainer(env, use_expert_rollouts=True)
    expert_policy = util.load_expert_policy(env)
    random_policy = util.make_blank_policy(env)
    gen_policy = trainer.policy

    assert expert_policy is not None
    assert random_policy is not None

    X, random_rews, gen_rews = [], [], []

    def add_single_data(policy, policy_name, lst):
        rew = util.rollout_total_reward(policy, env, n_episodes=n_episodes)
        lst.append(rew)
        print("{} reward:".format(policy_name), rew)

    def make_data():
        X.append(trainer.epochs_so_far)
        print("Epoch {}".format(trainer.epochs_so_far))
        # add_single_data(expert_policy, "expert", expert_rews)
        add_single_data(random_policy, "random", random_rews)
        add_single_data(gen_policy, "generator", gen_rews)

    make_data()
    for _ in range(n_plots):
        trainer.train(n_epochs=n_epochs_per_plot)
        make_data()

    # plt.plot(X, expert_rews, label="expert")
    plt.plot(X, gen_rews, label="generator")
    plt.plot(X, random_rews, label="random")
    plt.legend()
    _savefig_timestamp("plot_episode_reward_vs_time")


def plot_discriminator_loss(env='CartPole-v1', n_steps_per_plot=1000,
        n_plots=100, n_gen_warmup_steps=500):
    """
    Train the generator briefly, and then

    Train the discriminator to distinguish (unchanging) expert rollouts versus
    the unchanging random rollouts for a long time and plot discriminator loss.
    """
    trainer = _init_trainer(env, use_expert_rollouts=True)
    n_timesteps = len(trainer.expert_obs_old)
    (gen_obs_old, gen_act, gen_obs_new, _) = util.rollout_generate(
            trainer.policy, trainer.env, n_timesteps=n_timesteps)
    kwargs = dict(gen_obs_old=gen_obs_old, gen_act=gen_act,
            gen_obs_new=gen_obs_new)
    trainer.train_gen(n_steps=n_gen_warmup_steps)

    steps_so_far = 0
    def epoch():
        nonlocal steps_so_far
        trainer.train_disc(**kwargs, n_steps=n_steps_per_plot)
        steps_so_far += n_steps_per_plot

    X = []
    Y = []
    def add_plot():
        X.append(steps_so_far)
        Y.append(trainer.eval_disc_loss(**kwargs))
        print("step: {}".format(steps_so_far))
        print("loss: {}".format(Y[-1]))

    add_plot()
    for _ in tqdm.tnrange(n_plots, desc="discriminator"):
        epoch()
        add_plot()

    plt.plot(X, Y, label="discriminator loss")
    plt.legend()
    _savefig_timestamp("plot_discriminator_loss")


def plot_generator_loss(env='CartPole-v1', n_steps_per_plot=5000,
        n_plots=100, n_disc_warmup_steps=100):
    """
    Train the discriminator briefly, and then

    Train the generator to distinguish (unchanging) expert rollouts to
    confuse the discriminator, and plot discriminator loss.
    """
    trainer = _init_trainer(env, use_expert_rollouts=True)
    n_timesteps = len(trainer.expert_obs_old)

    (gen_obs_old, gen_act, gen_obs_new, _) = util.rollout_generate(
            trainer.policy, trainer.env, n_timesteps=n_timesteps)

    steps_so_far = 0
    def epoch():
        nonlocal steps_so_far
        trainer.train_gen(n_steps=n_steps_per_plot)
        steps_so_far += n_steps_per_plot

    X = []
    Y = []
    def add_plot():
        X.append(steps_so_far)
        Y.append(trainer.eval_disc_loss())
        print("step: {}".format(steps_so_far))
        print("disc loss: {}".format(Y[-1]))

    add_plot()
    for _ in tqdm.tnrange(n_plots, desc="generator"):
        epoch()
        add_plot()

    plt.plot(X, Y, label="discriminator loss")
    plt.legend()
    _savefig_timestamp("plot_generator_loss")


def plot_fight_loss(env='CartPole-v1',
        n_epochs=100,
        n_plots_each_per_epoch=10,
        n_disc_steps_per_plot=500,
        n_gen_steps_per_plot=50000,
        n_rollout_samples=1000,
        n_gen_plot_episodes=100,
        trainer_hook_fn=None,
        trainer=None):
    """
    Alternate between training the generator and discriminator.

    Every epoch:
    - Plot discriminator loss during discriminator training steps in blue and
    discriminator loss during generator training steps in red.
    - Plot the performance of the generator policy versus the performance of
      a random policy.
    """
    trainer = trainer or _init_trainer(env, use_expert_rollouts=True,
            n_rollout_samples=n_rollout_samples)
    trainer_hook_fn(trainer)
    n_timesteps = len(trainer.expert_obs_old)

    plot_idx = 0
    def epoch(gen_mode=False):
        nonlocal plot_idx
        if gen_mode:
            trainer.train_gen(n_steps=n_gen_steps_per_plot)
        else:
            trainer.train_disc(n_steps=n_disc_steps_per_plot)
        plot_idx += 1

    gen_data = ([], [])
    disc_data = ([], [])
    def add_plot_disc(gen_mode=False):
        """
        gen_mode (bool): Whether the generator or the discriminator is active.
          We use this to color the data points.
        """
        mode = "gen" if gen_mode else "dis"
        X, Y = gen_data if gen_mode else disc_data
        X.append(plot_idx)
        Y.append(trainer.eval_disc_loss())
        print("plot idx ({}): {}".format(mode, plot_idx), end=" ")
        print("disc loss: {}".format(Y[-1]))
    def show_plot_disc():
        plt.scatter(disc_data[0], disc_data[1], c='g', alpha=0.7, s=4,
                label="discriminator loss (dis step)")
        plt.scatter(gen_data[0], gen_data[1], c='r', alpha=0.7, s=4,
                label="discriminator loss (gen step)")
        plt.title("epoch={}".format(epoch_num))
        plt.legend()
        _savefig_timestamp("plot_fight_loss_disc")

    gen_ep_reward = []
    rand_ep_reward = []
    def add_plot_gen():
        env_vec = util.make_vec_env(env, 8)
        gen_policy = trainer.policy
        rand_policy = util.make_blank_policy(env)

        gen_rew = util.rollout_total_reward(gen_policy, env,
                n_episodes=n_gen_plot_episodes)/n_gen_plot_episodes
        rand_rew = util.rollout_total_reward(rand_policy, env,
                n_episodes=n_gen_plot_episodes)/n_gen_plot_episodes
        gen_ep_reward.append(gen_rew)
        rand_ep_reward.append(rand_rew)
        print("generator reward:", gen_rew)
        print("random reward:", rand_rew)
    def show_plot_gen():
        plt.title("Cartpole performance (expert=500)")
        plt.xlabel("epochs")
        plt.ylabel("Average reward per episode (n={})"
                .format(n_gen_plot_episodes))
        plt.plot(gen_ep_reward, label="avg gen ep reward", c="red")
        plt.plot(rand_ep_reward, label="avg random ep reward", c="black")
        plt.legend()
        _savefig_timestamp("plot_fight_epreward_gen")

    add_plot_disc(False)
    add_plot_gen()
    for epoch_num in tqdm.tnrange(n_epochs, desc="epoch"):
        for _ in range(n_plots_each_per_epoch):
            epoch(False)
            add_plot_disc(False)
        for _ in range(n_plots_each_per_epoch):
            epoch(True)
            add_plot_disc(True)
        add_plot_gen()

        show_plot_disc()
        show_plot_gen()
        if trainer_hook_fn:
            trainer_hook_fn(trainer)

    return trainer, gen_data, disc_data, gen_ep_reward


def _savefig_timestamp(prefix="", also_show=True):
    path = "output/{}_{}.png".format(prefix, datetime.datetime.now())
    plt.savefig(path)
    plt.show()

def _decor_tf_init(f):
    with tf.Session() as sess:
        pass

if __name__ == "__main__":
    plot_fight_loss()
