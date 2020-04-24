from .env_wrapper import EnvWrapper
import numpy as np


class BlueWrapper(EnvWrapper):
    def __init__(self, config):

        pos_control = config["pos_control"]
        actuator = 'motor'
        if pos_control: actuator='position'
        env_kwargs = dict(port = 1050,
                        visionnet_input = False,
                        unity = False,
                        world_path = '/home/demo/DoorGym/world_generator/world/pull_blue_right_v2_gripper_{}_lefthinge_single/'.format(actuator),
                        pos_control = pos_control,
                        ik_control = False)

        EnvWrapper.__init__(self, config['env'], env_kwargs)
        self.config = config

        print(self._true_action_space.high, self._true_action_space.low)
        print(self._norm_action_space.high, self._norm_action_space.low)

    def _convert_action(self, action):
        action = action.astype(np.float64)
        true_delta = self._true_action_space.high - self._true_action_space.low
        norm_delta = self._norm_action_space.high - self._norm_action_space.low
        action = (action - self._norm_action_space.low) / norm_delta
        action = action * true_delta + self._true_action_space.low
        action = action.astype(np.float32)
        return action

    def get_current_pos(self):
        return self.env.get_robot_joints()[:self.config["action_dim"]]

    def step(self, action):
        # print("norm action: ",action)
        assert self._norm_action_space.contains(action)
        action = self._convert_action(action)
        # print("converted action: ", action)

        if self.env.pos_control:
            # print("current joints: ", self.get_current_pos())
            action += self.get_current_pos()
            # print("combined joints: ", action)

        action = action.clip(self._true_action_space.low, self._true_action_space.high)
        assert self._true_action_space.contains(action)
        # print("clipped action: ", action)

        import sys
        sys.exit(1)

        next_state, reward, terminal, _ = self.env.step(action.ravel())
        return next_state, reward, terminal

    def normalise_state(self, state):
        return state

    def normalise_reward(self, reward):
        return reward