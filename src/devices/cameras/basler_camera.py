import glob
import logging
import multiprocessing as mp
import os
import time
from collections import deque

import cv2
from pypylon import pylon
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
        trigger_data, frame_buffer = video_writer_recv.recv()
        t_write_start = time.time()
        ntrig = trigger_data["ntrig"]
        obj_id = trigger_data["obj_id"]
        cam_serial = trigger_data["cam_serial"]
        frame = trigger_data["frame"]

        # Create output folder and filename
        output_file = f"{ntrig}_obj_id_{obj_id}_cam_{cam_serial}_frame_{frame}.mp4"  # noqa: E501
        output_filename = os.path.join(output_folder, output_file)

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


def basler_camera(
    cam_serial: str | int,
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
    tlf = pylon.TlFactory.GetInstance()
    info = pylon.DeviceInfo()
    info.SetSerialNumber(str(cam_serial))
    cam = pylon.InstantCamera(tlf.CreateDevice(info))

    # Create BGR converter
    converter = pylon.ImageFormatConverter()
    converter.OutputPixelFormat = pylon.PixelType_BGR8packed
    converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

    # Set essential camera parameters
    cam.Open()
    nodeFile = glob.glob(f"/home/benyishay_la/braid-configs/*{cam_serial}*.pfs")
    pylon.FeaturePersistence_Load(nodeFile[0], cam.GetNodeMap(), True)
    cam.Close()
    # cam.Open()
    # cam.TriggerSelector = "FrameStart"
    # cam.TriggerMode = "On"
    # cam.TriggerSource = "Line1"
    # cam.TriggerActivation = "RisingEdge"
    # # cam.SensorReadoutMode = "Fast"

    # # Set possible camera parameters from `params`
    # cam.ExposureTime = (
    #     1900  # params["highspeed"]["parameters"].get("ExposureTime", 1900)
    # )
    # # cam.Gain = params["highspeed"]["parameters"].get("Gain", 10)

    # Setup triggered writing variables
    time_before = params["highspeed"]["parameters"].get("time_before", 1)
    time_after = params["highspeed"]["parameters"].get("time_after", 2)
    fps = params["highspeed"]["parameters"].get("fps", 500)
    frames_before = int(time_before * fps)
    frames_after = int(time_after * fps)
    n_total_frames = int(frames_before + frames_after)
    frame_buffer = deque(maxlen=n_total_frames)
    i_frame = 0
    trigger_set = False
    started_capture = False

    # Initialize video writer process
    video_writer_recv, video_writer_send = mp.Pipe()
    video_writer_p = mp.Process(
        target=video_writer,
        args=(
            video_writer_recv,
            params["video_save_folder"],
        ),
        daemon=True,
    )
    video_writer_p.start()

    # Wait until all cameras reach barrier
    logging.debug("Waiting for all cameras to reach barrier.")
    camera_barrier.wait()

    # Start grabbing
    cam.StartGrabbing(pylon.GrabStrategy_OneByOne)
    logging.info(f"Camera {cam_serial} started grabbing.")

    # Start camera
    while not kill_event.is_set():
        if kill_event.is_set():
            break

        # Check for trigger
        trigger_set = trigger_recv.poll()

        # If trigger is set, get trigger data
        if trigger_set:
            trigger_data = trigger_recv.recv()
            trigger_data["cam_serial"] = cam_serial

        # Grab frame
        try:
            grabResult = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
        except pylon.TimeoutException:
            logging.warning("TimeoutException in camera grab.")
            continue

        frame_buffer.append(grabResult.GetArray())

        if trigger_set or started_capture:
            # Define that we want to start capturing frames
            started_capture = True
            i_frame += 1

            if i_frame == frames_after:
                # Send data to video writer
                video_writer_send.send([trigger_data, frame_buffer])
                logging.debug(f"Sent {len(frame_buffer)} frames to video writer.")

                # Reset counter and flag
                i_frame = 0
                started_capture = False

    logging.debug(f"Stopping camera {cam_serial}.")
    cam.StopGrabbing()


def start_highspeed_cameras(params: dict, kill_event: mp.Event):
    """a wrapper function to initialize a group of highspeed cameras

    Args:
        params (dict): parameters dict
        kill_event (mp.Event): kill event

    Returns:
        highspeed_cameras: a list containing the camera processes
        highspeed_cameras_pipes: a dict containing the camera pipes
    """
    # Create a synchronization barrier for the cameras
    camera_barrier = mp.Barrier(len(params["highspeed"]["cameras"]) + 1)
    logging.debug(
        f"Created camera barrier with {len(params['highspeed']['cameras'])} cameras."
    )
    # Start camera processes
    highspeed_cameras = []
    highspeed_cameras_pipes = {}

    # Loop over cameras
    for cam_name, cam_serial in params["highspeed"]["cameras"].items():
        highspeed_cameras_pipes[cam_name] = {}
        # Create a pipe for each camera
        (
            highspeed_cameras_pipes[cam_name]["recv"],
            highspeed_cameras_pipes[cam_name]["send"],
        ) = mp.Pipe()

        # Start the process
        logging.info(f"Creating camera {cam_name} with serial {cam_serial}.")
        p = mp.Process(
            target=basler_camera,
            args=(
                cam_serial,
                params,
                camera_barrier,
                highspeed_cameras_pipes[cam_name]["recv"],
                kill_event,
            ),
            name=f"Camera_{cam_serial}",
        )
        highspeed_cameras.append(p)

    return highspeed_cameras, highspeed_cameras_pipes, camera_barrier
