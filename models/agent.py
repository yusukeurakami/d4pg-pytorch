import shutil
import os
import time
from collections import deque
import torch

from utils.utils import OUNoise, make_gif, empty_torch_queue
from utils.logger import Logger
from env.utils import create_env_wrapper


class Agent(object):

    def __init__(self, config, policy, global_episode, n_agent=0, agent_type='exploration', log_dir=''):
        print(f"Initializing agent {n_agent}...")
        self.config = config
        self.n_agent = n_agent
        self.agent_type = agent_type
        self.max_steps = config['max_ep_length']
        self.num_episode_save = config['num_episode_save']
        self.num_step_save = config['num_step_save']
        self.global_episode = global_episode
        self.local_episode = 0
        self.log_dir = log_dir

        # Create environment
        self.env_wrapper = create_env_wrapper(config)
        self.ou_noise = OUNoise(dim=config["action_dim"], low=config["action_low"], high=config["action_high"])
        self.ou_noise.reset()

        self.actor = policy
        print("Agent ", n_agent, self.actor.device)

        # Logger
        if self.n_agent==0:
            log_path = f"{log_dir}/agent-{n_agent}"
            self.logger = Logger(log_path)

    def update_actor_learner(self, learner_w_queue, training_on):
        """Update local actor to the actor from learner. """
        if not training_on.value:
            return
        try:
            source = learner_w_queue.get_nowait()
        except:
            return
        target = self.actor
        for target_param, source_param in zip(target.parameters(), source):
            w = torch.tensor(source_param).float()
            target_param.data.copy_(w)
        del source

    def run(self, training_on, replay_queue, learner_w_queue, update_step):
        # Initialise deque buffer to store experiences for N-step returns
        self.exp_buffer = deque()

        best_reward = -float("inf")
        rewards = []
        while training_on.value:
            episode_reward = 0
            num_steps = 0
            self.local_episode += 1
            self.global_episode.value += 1
            self.exp_buffer.clear()

            if self.local_episode % 100 == 0:
                print(f"Agent: {self.n_agent}  episode {self.local_episode}")

            succeeded = 0.0
            best_succeeded = 0.0

            ep_start_time = time.time()
            state = self.env_wrapper.reset()
            current_pos = state[:self.config["action_dim"]]
            self.ou_noise.reset()
            done = False
            while not done:
                action = self.actor.get_action(state)
                # print("action mean: ", action)
                if self.agent_type == "exploration":
                    action = self.ou_noise.get_action(action, num_steps)
                    action = action.squeeze(0)
                    # print("action with noise :", action)
                else:
                    action = action.detach().cpu().numpy().flatten()

                next_a = action
                # if self.config["pos_control"]:
                #     # print("current pos: ",current_pos)
                #     next_a += current_pos
                for _ in range(self.config["action_repeat"]):
                    next_state, reward, done = self.env_wrapper.step(next_a) # Step
                    if done:
                        break
                current_pos = next_state[:self.config["action_dim"]]

                # next_state, reward, done = self.env_wrapper.step(action)

                episode_reward += reward

                state = self.env_wrapper.normalise_state(state)
                reward = self.env_wrapper.normalise_reward(reward)

                self.exp_buffer.append((state, action, reward))

                # We need at least N steps in the experience buffer before we can compute Bellman
                # rewards and add an N-step experience to replay memory
                if len(self.exp_buffer) >= self.config['n_step_returns']:
                    state_0, action_0, reward_0 = self.exp_buffer.popleft()
                    discounted_reward = reward_0
                    gamma = self.config['discount_rate']
                    for (_, _, r_i) in self.exp_buffer:
                        discounted_reward += r_i * gamma
                        gamma *= self.config['discount_rate']
                    # We want to fill buffer only with form explorator
                    if self.agent_type == "exploration":
                        try:
                            replay_queue.put_nowait([state_0, action_0, discounted_reward, next_state, done, gamma])
                        except:
                            pass

                state = next_state

                if done or num_steps >= self.max_steps:
                    # if self.n_agent:
                    #     print("episode done. Step was ",num_steps)
                    # add rest of experiences remaining in buffer
                    while len(self.exp_buffer) != 0:
                        state_0, action_0, reward_0 = self.exp_buffer.popleft()
                        discounted_reward = reward_0
                        gamma = self.config['discount_rate']
                        for (_, _, r_i) in self.exp_buffer:
                            discounted_reward += r_i * gamma
                            gamma *= self.config['discount_rate']
                        if self.agent_type == "exploration":
                            try:
                                replay_queue.put_nowait([state_0, action_0, discounted_reward, next_state, done, gamma])
                            except:
                               pass
                    break

                num_steps += 1

            #
            # Log metrics
            step = update_step.value
            if self.n_agent==0:
                self.logger.scalar_summary("agent/reward", episode_reward, step)
                self.logger.scalar_summary("agent/episode_timing", time.time() - ep_start_time, step)

            rewards.append(episode_reward)
            if self.agent_type == "exploration" and self.local_episode % self.config['update_agent_ep'] == 0:
                self.update_actor_learner(learner_w_queue, training_on)

            ###########################
            if self.local_episode%100 == 0:
                print("evaluate")
                avg_reward = 0.
                episodes = 20
                succeeded = 0
                rewards = []
                for _ in range(episodes):
                    episode_reward = 0
                    num_steps = 0

                    state = self.env_wrapper.reset()
                    current_pos = state[:self.config["action_dim"]]
                    self.ou_noise.reset()
                    done = False
                    while not done:
                        action = self.actor.get_action(state)
                        action = action.detach().cpu().numpy().flatten()

                        next_a = action
                        # if self.config["pos_control"]:
                        #     # print("current pos: ",current_pos)
                        #     next_a += current_pos
                        for _ in range(self.config["action_repeat"]):
                            next_state, reward, done = self.env_wrapper.step(next_a) # Step
                            if done:
                                break
                        current_pos = next_state[:self.config["action_dim"]]

                        # next_state, reward, done = self.env_wrapper.step(action)

                        episode_reward += reward

                        state = self.env_wrapper.normalise_state(state)
                        reward = self.env_wrapper.normalise_reward(reward)

                        state = next_state

                        if done or num_steps >= self.max_steps:
                            if abs(self.env_wrapper.env.env.get_doorangle())>=0.2:
                                succeeded += 1
                            # else:
                            #     print("not opened")

                        num_steps += 1

                avg_reward += episode_reward
            
                avg_reward /= episodes
                succeeded /= episodes
                if self.n_agent==0:
                    self.logger.scalar_summary("agent/test", avg_reward, step)
                    self.logger.scalar_summary("agent/success_rate", succeeded, step)
                print("----------------------------------------")
                print("Test Episodes: {}, Avg. Reward: {}, Success rate {}% per {} trials".format(episodes, round(avg_reward, 2), round(succeeded, 2), episodes))
                print("----------------------------------------")

            # Saving agent
            reward_outperformed = succeeded - best_succeeded > self.config["save_success_rate_threshold"]
            # reward_outperformed = episode_reward - best_reward > self.config["save_reward_threshold"]
            time_to_save = self.local_episode % self.num_episode_save == 0
            if self.n_agent == 0 and (time_to_save or reward_outperformed):
                # print(time_to_save, reward_outperformed)
                # if episode_reward > best_reward:
                #     best_reward = episode_reward
                if succeeded > best_succeeded:
                    best_succeeded = succeeded
                self.save(f"agent-{self.n_agent}_local-episode-{self.local_episode}_step-{step}_success-{best_succeeded:4f}")
            ###########################

        empty_torch_queue(replay_queue)
        print(f"Agent {self.n_agent} done.")

    def save(self, checkpoint_name):
        print("save the model", checkpoint_name)
        process_dir = f"{self.log_dir}/agent_{self.n_agent}"
        if not os.path.exists(process_dir):
            os.makedirs(process_dir)
        model_fn = f"{process_dir}/{checkpoint_name}.pt"
        torch.save(self.actor, model_fn)

    def save_replay_gif(self, output_dir_name):
        import matplotlib.pyplot as plt

        dir_name = output_dir_name
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)

        state = self.env_wrapper.reset()
        for step in range(self.max_steps):
            action = self.actor.get_action(state)
            action = action.cpu().detach().numpy()
            next_state, reward, done = self.env_wrapper.step(action)
            img = self.env_wrapper.render()
            plt.imsave(fname=f"{dir_name}/{step}.png", arr=img)
            state = next_state
            if done:
                break

        fn = f"{self.config['env']}-{self.config['model']}-{step}.gif"
        make_gif(dir_name, f"{self.log_dir}/{fn}")
        shutil.rmtree(dir_name, ignore_errors=False, onerror=None)
        print("fig saved to ", f"{self.log_dir}/{fn}")