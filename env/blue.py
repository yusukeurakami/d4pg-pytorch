from .env_wrapper import EnvWrapper


class BlueWrapper(EnvWrapper):
    def __init__(self, config):

        pos_control = config["pos_control"]
        actuator = 'motor'
        if pos_control: actuator='position'
        env_kwargs = dict(port = 1050,
                        visionnet_input = False,
                        unity = False,
                        world_path = '/u/home/urakamiy/doorgym/world_generator/world/pull_blue_right_v2_gripper_{}_lefthinge_single/'.format(actuator),
                        pos_control = pos_control,
                        ik_control = False)

        EnvWrapper.__init__(self, config['env'], env_kwargs)
        self.config = config

    def normalise_state(self, state):
        return state

    def normalise_reward(self, reward):
        return reward