import numpy as np
from collections import deque


class RealTimeHeadingCalculator:
    def __init__(self, window_size=10):
        self.window_size = window_size
        self.xvel_buffer = deque(maxlen=window_size)
        self.yvel_buffer = deque(maxlen=window_size)
        self.zvel_buffer = deque(maxlen=window_size)

    def add_data_point(self, xvel, yvel, zvel):
        self.xvel_buffer.append(xvel)
        self.yvel_buffer.append(yvel)
        self.zvel_buffer.append(zvel)

    def calculate_smoothed_velocities(self):
        smoothed_xvel = np.mean(self.xvel_buffer)
        smoothed_yvel = np.mean(self.yvel_buffer)
        smoothed_zvel = np.mean(self.zvel_buffer)
        return smoothed_xvel, smoothed_yvel, smoothed_zvel

    def calculate_heading(self):
        smoothed_xvel, smoothed_yvel, smoothed_zvel = (
            self.calculate_smoothed_velocities()
        )
        heading = np.arctan2(smoothed_yvel, smoothed_xvel)
        return heading


def check_position(pos, trigger_params):
    # calculate x position corrected for the center of the arena
    radius = (
        (pos["x"] - trigger_params["center_x"]) ** 2
        + (pos["y"] - trigger_params["center_y"]) ** 2
    ) ** 0.5
    if trigger_params["type"] == "radius":
        in_position = (
            radius < trigger_params["min_radius"]
            and trigger_params["zmin"] <= pos["z"] <= trigger_params["zmax"]
        )
    elif trigger_params["type"] == "zone":
        in_position = (
            trigger_params["zmin"] <= pos["z"] <= trigger_params["zmax"]
            and trigger_params["xmin"] <= pos["x"] <= trigger_params["xmax"]
            and trigger_params["ymin"] <= pos["y"] <= trigger_params["ymax"]
        )

    return in_position
