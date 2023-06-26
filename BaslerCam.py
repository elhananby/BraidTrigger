from collections.abc import Callable, Iterable, Mapping
from typing import Any
from pypylon import pylon as py
import multiprocessing as mp
from collections import deque
import threading
from queue import Queue
from vidgear.gears import WriteGear


class BaslerCam(mp.Process):
    def __init__(
        self,
        group: None = None,
        target: Callable[..., object] | None = None,
        name: str | None = None,
        args: Iterable[Any] = ...,
        kwargs: Mapping[str, Any] = ...,
        *,
        daemon: bool | None = None
    ) -> None:
        super().__init__(group, target, name, args, kwargs, daemon=daemon)

        # Get camera serial number
        self.serial = kwargs.get("serial", None)
        if self.serial is None:
            raise ValueError("Serial number is required.")
            return

        # Save kwargs
        self.kwargs = kwargs

        for arg in args:
            setattr(self, arg, arg)

        # setup camera
        self.tlf = py.TlFactory.GetInstance()
        self.info = py.DeviceInfo()
        self.info.SetSerialNumber(str(self.serial))
        self.cam = py.InstantCamera(self.tlf.CreateDevice(self.info))

        # setup frame buffer
        self.frame_buffer = Queue(maxsize=self.kwargs("frame_buffer_size", 100))

    def _video_writer(self, filename, frames):
        output_params = {
            "-input_framerate": 25,
            "-vcodec": "h264_nvenc",
            "-preset": "fast",
            "-rc": "cbr_ld_hq",
            "-disable_force_termination": True,
        }

        video_writer = WriteGear(
            output=filename,
            logging=False,
            **output_params,
        )

        for frame in frames:
            video_writer.write(frame)

        video_writer.close()

    def _set_parameters(self, parameter: str):
        self.cam.Open()
        self.cam.TriggerSelector = self.kwargs("trigger_selector", "FrameStart")
        self.cam.TriggerSource = self.kwargs("trigger_source", "Line1")
        self.cam.TriggerActivation = self.kwargs("trigger_activation", "RisingEdge")
        self.cam.TriggerMode = self.kwargs("trigger_mode", "On")
        self.cam.ExposureMode = self.kwargs("exposure_mode", "TriggerWidth")
        self.cam.ExposureTime = self.kwargs("exposure_time", 1000)
        self.cam.Gain = self.kwargs("gain", 0)
        self.cam.SensorReadoutMode = self.kwargs("sensor_readout_mode", "Fast")
        self.cam.Close()

    def _converter(self):
        # setup converter to convert to BGR8
        self.converter = py.ImageFormatConverter()
        self.converter.OutputPixelFormat = py.PixelType_BGR8packed
        self.converter.OutputBitAlignment = py.OutputBitAlignment_MsbAligned

    def run(self):
        # wait for barrier, if barrier is set
        if self.barrier:
            self.barrier.wait()

        # start grabbing
        self.cam.StartGrabbing(py.GrabStrategy_OneByOne)
        try:
            while True:
                with self.cam.RetrieveResult(
                    5000, py.TimeoutHandling_ThrowException
                ) as grabResult:
                    image = self.converter.Convert(grabResult)
                    img = image.GetArray()
                    self.frame_buffer.append(img)

        except KeyboardInterrupt:
            pass

        self.stop()

    def stop(self):
        self.cam.StopGrabbing()
