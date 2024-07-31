import logging
import multiprocessing as mp
import os
import time
from collections import deque

import cv2
from ximea import xiapi
from vidgear.gears import WriteGear


def video_writer(video_writer_recv: mp.Pipe, output_folder: str):
    """a process/thread function to loop over a pipe and write frames to a video file.

    Args:
        video_writer_recv (mp.Pipe): incoming data pipe
    """
    output_params = {
        "-input_framerate": 25,
        "-vcodec": "h264_nvenc",
        "-preset": "slow",
        "-cq": "18",
        "-disable_force_termination": True,
    }

    while True:
        logging.info("Waiting for data to write to video.")
        trigger_data, frame_buffer = video_writer_recv.recv()
        if trigger_data == "kill":
            break

        logging.info(f"Recieved trigger data: {trigger_data}")
        t_write_start = time.time()
        ntrig = trigger_data["ntrig"]
        obj_id = trigger_data["obj_id"]
        cam_serial = trigger_data["cam_serial"]
        frame = trigger_data["frame"]

        # Create output folder and filename
        output_file = f"{ntrig}_obj_id_{obj_id}_cam_{cam_serial}_frame_{frame}.mp4"  # noqa: E501
        output_filename = os.path.join(output_folder, output_file)

        # check if folder exists; if not create it
        os.makedirs(output_folder, exist_ok=True)

        logging.debug("Starting WriteGear videowriter.")
        video_writer = WriteGear(output=output_filename, logging=False, **output_params)
        logging.debug(f"Writing video to {os.path.basename(output_filename)}")

        # Loop over frames and write to video
        for frame in frame_buffer:
            video_writer.write(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
        logging.info(
            f"Finished writing video with length {len(frame_buffer)} to {os.path.basename(output_filename)} in {time.time()-t_write_start:2f} seconds."  # noqa: E501
        )
        video_writer.close()

        # copy file to external drive
        # copy_dest = os.makedirs(
        #     os.path.join(
        #         "/media/benyishay_la/8tb_data/Videos", os.path.basename(output_folder)
        #     ),
        #     exist_ok=True,
        # )
        # shutil.copy(output_filename, os.path.join(copy_dest, output_file))


def ximea_camera(
    cam_serial: str | int | None,
    params: dict,
    camera_barrier: mp.Barrier,
    trigger_recv: mp.Pipe,
    kill_event: mp.Event,
):
    """Triggered camera function, to record frames before and after a trigger.

    Args:
        cam_serial (str | int): serial number of the camera
        params (dict): parameters dictionary
        camera_barrier (mp.Barrier): barrier to synchronize cameras
        trigger_recv (mp.Pipe): incoming trigger pipe
        kill_event (mp.Event): kill event
    """

    # Connect to camera
    cam = xiapi.Camera()
    if cam_serial is not None:
        cam.open_device_by_SN(str(cam_serial))
    else:
        cam.open_device()

    fps = params["highspeed"]["parameters"].get("fps", 200)

    # Setup camera parameters
    cam.set_exposure(2000)
    cam.set_framerate(fps)
    cam.set_width(2496)
    cam.set_height(2496)
    cam.set_imgdataformat("XI_MONO8")
    cam.set_acq_timing_mode("XI_ACQ_TIMING_MODE_FRAME_RATE_LIMIT")
    cam.disable_aeag()
    cam.enable_recent_frame()
    img = xiapi.Image()

    # Setup triggered writing variables
    time_before = params["highspeed"]["parameters"].get("time_before", 1)
    time_after = params["highspeed"]["parameters"].get("time_after", 2)

    frames_before = int(time_before * fps)
    frames_after = int(time_after * fps)

    pre_buffer = deque(maxlen=frames_before)
    pre_nframes = deque(maxlen=frames_before)
    pre_acq_nframes = deque(maxlen=frames_before)

    post_buffer = deque(maxlen=frames_after)
    post_nframes = deque(maxlen=frames_after)
    post_acq_nframes = deque(maxlen=frames_after)
    switch = False

    # Initialize video writer process
    video_writer_recv, video_writer_send = mp.Pipe()
    video_writer_p = mp.Process(
        target=video_writer,
        args=(
            video_writer_recv,
            params["video_save_folder"],
        ),
    )
    video_writer_p.start()

    # Wait until all cameras reach barrier
    logging.debug("Waiting for all cameras to reach barrier.")
    camera_barrier.wait()

    # Start grabbing
    logging.info(f"Camera {cam_serial} started grabbing.")
    cam.start_acquisition()

    # Start camera
    while True:
        if kill_event.is_set() and not switch:
            break

        # Check for trigger
        trigger_set = trigger_recv.poll()

        # If trigger is set, get trigger data
        if trigger_set:
            logging.info(f"Camera {cam_serial} recieved trigger.")
            logging.info("Switching buffers.")
            trigger_data = trigger_recv.recv()
            trigger_data["cam_serial"] = cam_serial
            switch = True
            switch_time = time.time()

        # Grab frame
        cam.get_image(img)
        frame = img.get_image_data_numpy()
        nframe = img.nframe
        acq_nframe = img.acq_nframe

        if not switch:
            pre_buffer.append(frame)
            pre_nframes.append(nframe)
            pre_acq_nframes.append(acq_nframe)
        else:
            post_buffer.append(frame)
            post_nframes.append(nframe)
            post_acq_nframes.append(acq_nframe)

        if len(post_buffer) == post_buffer.maxlen:
            logging.debug(f"Switch took {time.time()-switch_time:.2f} seconds.")
            logging.debug(f"Expected to take {time_after:.2f} seconds.")
            logging.info("Buffer full, sending data to video writer.")
            video_writer_send.send([trigger_data, list(pre_buffer) + list(post_buffer)])
            pre_buffer.clear()
            post_buffer.clear()
            switch = False
            break

    import numpy as np

    logging.debug(
        f"pre_nframes mean: {np.mean(np.diff(pre_nframes))}, std: {np.std(np.diff(pre_nframes))}"
    )
    logging.debug(
        f"pre_acq_nframes mean: {np.mean(np.diff(pre_acq_nframes))}, std: {np.std(np.diff(pre_acq_nframes))}"
    )

    logging.debug(
        f"post_nframes mean: {np.mean(np.diff(post_nframes))}, std: {np.std(np.diff(post_nframes))}"
    )
    logging.debug(
        f"post_acq_nframes mean: {np.mean(np.diff(post_acq_nframes))}, std: {np.std(np.diff(post_acq_nframes))}"
    )

    logging.debug(f"Stopping camera {cam_serial}.")
    cam.stop_acquisition()
    cam.close_device()

    logging.debug("Stopping video writer process.")
    video_writer_send.send(["kill", None])
    video_writer_p.join()


if __name__ == "__main__":
    # set logging level to DEUBG
    logging.basicConfig(level=logging.DEBUG)

    # create mp variables
    barrier = mp.Barrier(2)
    trigger_send, trigger_recv = mp.Pipe()
    kill_event = mp.Event()

    # create camera process
    camera_process = mp.Process(
        target=ximea_camera,
        args=(
            None,
            {
                "highspeed": {
                    "parameters": {"time_before": 1, "time_after": 2, "fps": 200}
                },
                "video_save_folder": "test_folder",
            },
            barrier,
            trigger_recv,
            kill_event,
        ),
    )

    camera_process.start()

    # waiting until all cameras reach barrier
    barrier.wait()

    # waiting a few seconds for frames to fill the buffer
    time.sleep(5)

    # sending trigger
    trigger_send.send({"ntrig": 1, "obj_id": 1, "frame": 1})

    # waiting for the video writer to finish
    time.sleep(5)

    # send kill signal
    kill_event.set()

    # join camera process
    camera_process.join()
