import copy
import logging
import multiprocessing as mp
import os
import threading
import time
from queue import Queue
import numpy as np
import pandas as pd
import pygame
import math

from csv_writer import CsvWriter

os.environ["SDL_VIDEO_WINDOW_POS"] = "%d,%d" % (0, 0)

WIDTH = 640
HEIGHT = 128
HZ = 60
PIXEL_SIZE_CM = 0.4
D = 25  # distance to screen in cm


def find_rv_timecourse(theta_min_in, theta_max_in, r_v_ratio, delta_t):
    display_frequency = 1 / delta_t  # in Hz

    theta_max = np.deg2rad(theta_max_in)
    theta_min = np.deg2rad(theta_min_in)

    min_collision_time = r_v_ratio / np.tan(
        theta_max / 2
    )  # time to collision for disc at theta_max.
    max_collision_time = r_v_ratio / np.tan(
        theta_min / 2
    )  # time to collision for disc at theta_min.
    total_collision_time = max_collision_time - min_collision_time
    num_frames = math.ceil(
        total_collision_time * display_frequency
    )  # round up so we cover at least theta_min to theta_max.

    time_theta_array = np.zeros((num_frames, 2))

    time_theta_array[:, 0] = np.arange(
        -min_collision_time, -max_collision_time, -delta_t
    )
    time_theta_array[:, 1] = (
        (180 / np.pi) * 2 * np.arctan2(r_v_ratio, (np.abs(time_theta_array[:, 0])))
    )

    return time_theta_array


def stimuli(
    trigger_event: mp.Event,
    kill_event: mp.Event,
    mp_dict: mp.Manager().dict,
    barrier: mp.Barrier,
    got_trigger_counter: mp.Value,
    lock: mp.Lock,
    params: dict,
):
    # start csv writer
    csv_queue = Queue()
    csv_kill = threading.Event()
    csv_writer = CsvWriter(
        csv_file=params["folder"] + "/stim.csv",
        queue=csv_queue,
        kill_event=csv_kill,
    ).start()

    # initialize pygame
    pygame.init()

    # initialize screen
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.NOFRAME)

    # initialize clock
    clock = pygame.time.Clock()

    # background image
    if params["stim_params"]["static"]["active"]:
        bg = pygame.image.load(params["stim_params"]["static"]["image"])
        bg = pygame.transform.scale(bg, (WIDTH, HEIGHT))
    else:
        bg = pygame.Surface((WIDTH, HEIGHT))
        bg.fill("white")

    loom_stim = params["stim_params"]["looming"]

    # looming stimulus
    if loom_stim["active"]:
        looms_df = define_looming(
            loom_stim["duration"], loom_stim["radius"], loom_stim["position"]
        )
        circle_color = loom_stim["color"]
        start_loom = False

    # wait barrier
    logging.debug("Waiting for barrier")
    barrier.wait()
    logging.info("Barrier passed")
    trigger = False

    try:
        while True:
            # check if the kill event is set
            if kill_event.is_set():
                break

            # fill the screen with image/color
            screen.blit(bg, (0, 0))
            if trigger_event.is_set() and not trigger:
                data = copy.deepcopy(mp_dict)
                with lock:
                    got_trigger_counter.value += 1
                trigger = True
                logging.info("Got data from trigger event, set counter+=1")

            if loom_stim:
                # test if the trigger event is set
                if trigger and not start_loom:
                    logging.debug("Got data from trigger event")
                    start_loom = True  # set the start_loom flag to True

                    data["stimulus_start_time"] = time.time()

                    # get the parameters for the looming circle
                    curr_looming = looms_df.sample()
                    x = curr_looming["positions"].values[0]
                    y = HEIGHT // 2
                    radii = iter(curr_looming["radii_px"].values[0])

                    # save the parameters for the looming circle
                    data["looming_pos_x"] = curr_looming["positions"].values[0]
                    data["looming_pos_y"] = HEIGHT // 2
                    data["looming_radius"] = curr_looming["radius"].values[0]
                    data["looming_duration"] = curr_looming["duration"].values[0]

                    # wait for all other processes to process the trigger
                    # csv_queue.put(data)
                    trigger = False

                # if the start_loom flag is set, draw the circle
                if start_loom:
                    try:
                        radius = next(radii)
                    except StopIteration:
                        radius = 0
                        start_loom = False
                        data["stimulus_end_time"] = time.time()
                        csv_queue.put(data)
                        continue

                    # draw the circle
                    pygame.draw.circle(screen, circle_color, (x, y), radius)

                    # wraparound the x position if the circle goes off the screen
                    if x - radius < 0:
                        pygame.draw.circle(screen, circle_color, (x + WIDTH, y), radius)
                    elif x + radius > WIDTH:
                        pygame.draw.circle(screen, circle_color, (x - WIDTH, y), radius)

            pygame.display.flip()
            clock.tick(60)

    except KeyboardInterrupt:
        kill_event.set()

    pygame.quit()
    csv_kill.set()
    try:
        csv_writer.join()
    except AttributeError:
        pass

    logging.info("Stimuli process terminated.")


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    fig = plt.figure()
    for duration in [300, 500, 700, 100]:
        loom = define_looming(duration=duration, max_radius=64, position=WIDTH // 2)
        plt.plot(
            np.arange(0, len(loom["radii_px"].iloc[0])),
            loom["radii_px"].iloc[0],
            label=duration,
        )
    plt.legend()
    plt.show()
