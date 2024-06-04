import argparse
import json
import os
import subprocess
import time
from collections import deque

import numpy as np
import tomllib
from modules.messages import Publisher

from modules.utils.csv_writer import CsvWriter
from modules.utils.files import (
    check_braid_running,
    copy_files_to_folder,
    get_video_output_folder,
)
from modules.utils.flydra_proxy import Flydra2Proxy
from modules.utils.hardware import (
    create_arduino_device,
    initialize_backlighting_power_supply,
)
from modules.utils.opto import check_position, trigger_opto


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


def main(params_file: str, root_folder: str, args: argparse.Namespace):
    """Main BraidTrigger function. Starts up all processes and triggers.
    Loop over data incoming from the flydra2 proxy and tests if a trigger should be sent.

    Args:
        params_file (str): a path to the params.toml file
        root_folder (str): the root folder where the experiment folder will be created
    """

    # Load params
    with open(params_file, "rb") as f:
        params = tomllib.load(f)

    # Check if braidz is running (see if folder was created)
    params["folder"] = check_braid_running(root_folder, args.debug)
    braid_folder = params["folder"]

    # Copy the params file to the experiment folder
    copy_files_to_folder(braid_folder, params_file)

    # Set power supply voltage (for backlighting)
    if not args.debug:
        ps = initialize_backlighting_power_supply()

    # Connect to arduino
    if params["opto_params"].get("active", False):
        opto_trigger_board = create_arduino_device(
            port=params["arduino_devices"]["opto_trigger"]
        )

    # Connect to flydra2 proxy
    braid_proxy = Flydra2Proxy()

    # create data publisher
    pub = Publisher(pub_port=5556, handshake_port=5557)

    if args.plot:
        import zmq

        context = zmq.Context()
        pub_plot = context.socket(zmq.PUB)
        pub_plot.bind("tcp://*:12345")
        subprocess.Popen(["python", "modules/plotting.py"])

    # Connect to cameras
    if params["highspeed"].get("active", False):
        params["video_save_folder"] = get_video_output_folder(braid_folder)
        # start camera here
        pub.wait_for_subscriber()
        pub.publish("", params["video_save_folder"])

    # check if any visual stimuli is active and start the visual stimuli process
    if any(
        [value.get("active", False) for key, value in params["stim_params"].items()]
    ):
        subprocess.Popen(
            [
                "python",
                "./modules/visual_stimuli.py",
                f"{params_file}",
                "--base_dir",
                f"{braid_folder}",
            ]
        )
        pub.wait_for_subscriber()

    trigger_params = params["trigger_params"]

    csv_writer = CsvWriter(os.path.join(braid_folder, "opto.csv"))

    # initialize main loop parameters
    obj_ids = []
    obj_birth_times = {}
    headings = {}
    last_trigger_time = time.time()
    ntrig = 0

    # Start main loop
    try:
        for data in braid_proxy.data_stream():
            tcall = time.time()  # Get current time

            try:
                msg_dict = data["msg"]
            except KeyError:
                continue

            # Check for first "birth" message
            if "Birth" in msg_dict:
                curr_obj_id = msg_dict["Birth"]["obj_id"]
                obj_ids.append(curr_obj_id)
                obj_birth_times[curr_obj_id] = tcall
                headings[curr_obj_id] = RealTimeHeadingCalculator()
                continue

            # Check for "update" message
            elif "Update" in msg_dict:
                curr_obj_id = msg_dict["Update"]["obj_id"]

                # Calculate heading direction
                if curr_obj_id not in headings:
                    headings[curr_obj_id] = RealTimeHeadingCalculator()
                headings[curr_obj_id].add_data_point(
                    msg_dict["Update"]["xvel"],
                    msg_dict["Update"]["yvel"],
                    msg_dict["Update"]["zvel"],
                )

                if curr_obj_id not in obj_ids:
                    obj_ids.append(curr_obj_id)
                    obj_birth_times[curr_obj_id] = tcall
                    continue

            # Check for "death" message
            elif "Death" in msg_dict:
                curr_obj_id = msg_dict["Death"]
                if curr_obj_id in obj_ids:
                    obj_ids.remove(curr_obj_id)
                continue

            else:
                continue

            # if the trajectory is too short, skip
            if (tcall - obj_birth_times[curr_obj_id]) < trigger_params[
                "min_trajectory_time"
            ]:
                # logging.warning(f"Trajectory too short for object {curr_obj_id}")
                continue

            # if the trigger interval is too short, skip
            if tcall - last_trigger_time < trigger_params["min_trigger_interval"]:
                # logging.warning(f"Trigger interval too short for object {curr_obj_id}")
                continue

            # Get position and radius
            pos = msg_dict["Update"]

            # Calculate heading direction
            if args.plot:
                pub_plot.send_string(f"{pos['x']} {pos['y']} {pos['z']}")

            if check_position(pos, trigger_params):
                # Update last trigger time
                ntrig += 1
                last_trigger_time = tcall

                # Add trigger time to dict
                pos["trigger_time"] = last_trigger_time
                pos["ntrig"] = ntrig
                pos["main_timestamp"] = tcall
                pos["heading_direction"] = headings[curr_obj_id].calculate_heading()

                # Opto Trigger
                if params["opto_params"].get("active", False):
                    pos = trigger_opto(opto_trigger_board, trigger_params, pos)

                pub.publish("", json.dumps(pos))

                # Write data to csv
                csv_writer.write(pos)

    except KeyboardInterrupt:
        ps.set_voltage(0)
        pub.publish("", "kill")


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(processName)s: %(asctime)s - %(message)s",
    )

    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument("--plot", action="store_true", default=False)
    args = parser.parse_args()

    # Start main function
    print("Starting main function.")
    main(
        params_file="./params.toml",
        root_folder="/home/buchsbaum/mnt/DATA/Experiments/",
        args=args,
    )
