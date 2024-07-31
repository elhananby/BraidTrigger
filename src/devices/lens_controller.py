import argparse
import csv
import json
import os
import time
from typing import Dict, Tuple, Optional

import numpy as np
import pandas as pd
import requests
import toml
from sklearn.linear_model import LinearRegression

from utils.log_config import setup_logging
from utils.liquid_lens import LiquidLens

# Setup logging
logger = setup_logging(logger_name="LensController", level="INFO", color="cyan")
LENS_RESPONSE_TIME = 0.02  # 20 ms in seconds


class LensController:
    def __init__(
        self,
        device_address: str,
        braidz_url: str,
        params_file: str,
        save_folder: str = "",
        margins: float = 0.05,
    ):
        self.device_address = device_address
        self.braidz_url = braidz_url
        self.params_file = params_file
        self.save_folder = save_folder
        self.margins = margins

        self.tracking_start_time = time.time()
        self.tcall = time.time()
        self.current_tracked_object = None
        self.last_update = time.time()

        self.session = None
        self.r = None
        self.events_url = None
        self.device = None
        self.model = None
        self.bounds = None
        self.csv_file = None
        self.csv_writer = None

        self.setup()

    def setup(self) -> None:
        """Initialize all components of the LensController."""
        self.bounds = self._read_params()
        self._setup_braidz_proxy()
        self.model = self._setup_calibration()
        self._setup_device()
        self._setup_csv_writer()

    def _read_params(self) -> Dict[str, Tuple[float, float]]:
        """Read parameters from the params file and compute bounds."""
        logger.debug(f"Reading parameters from {self.params_file}")
        with open(self.params_file, "r") as f:
            params = toml.load(f)
        trigger_params = params["trigger_params"]
        return {
            "x": (
                trigger_params["xmin"] - self.margins,
                trigger_params["xmax"] + self.margins,
            ),
            "y": (
                trigger_params["ymin"] - self.margins,
                trigger_params["ymax"] + self.margins,
            ),
            "z": (
                trigger_params["zmin"] - self.margins,
                trigger_params["zmax"] + self.margins,
            ),
        }

    def _setup_device(self) -> None:
        """Setup the liquid lens controller."""
        logger.debug(f"Connecting to liquid lens controller at {self.device_address}")
        self.device = LiquidLens(port=self.device_address, debug=False)
        self.device.to_focal_power_mode()

    def _set_focalpower(self, focal_power: float) -> None:
        """Set the focal power of the liquid lens."""
        try:
            self.device.set_diopter(focal_power)
        except Exception as e:
            logger.error(f"Error setting focal power: {e}")

    def _setup_calibration(self) -> LinearRegression:
        """Setup the calibration for the liquid lens controller."""
        try:
            calibration = pd.read_csv(
                "/home/buchsbaum/lens_calibration/liquid_lens_calibration.csv"
            )
            X = calibration["distance"].values.reshape(-1, 1)
            y = calibration["dpt"].values
            model = LinearRegression()
            model.fit(X, y)
            return model
        except Exception as e:
            logger.error(f"Error setting up calibration: {e}")
            raise

    def _setup_braidz_proxy(self) -> None:
        """Setup the Braidz proxy connection."""
        self.session = requests.Session()
        try:
            r = self.session.get(self.braidz_url)
            r.raise_for_status()
            self.events_url = f"{self.braidz_url}events"
            self.r = self.session.get(
                self.events_url,
                stream=True,
                headers={"Accept": "text/event-stream"},
            )
        except requests.RequestException as e:
            logger.error(f"Failed to connect to {self.braidz_url}: {e}")
            raise

    def _parse_chunk(self, chunk: str) -> Dict:
        """Parse a chunk of data from the event stream."""
        lines = chunk.strip().split("\n")
        if (
            len(lines) != 2
            or lines[0] != "event: braid"
            or not lines[1].startswith("data: ")
        ):
            raise ValueError("Invalid chunk format")
        buf = lines[1][len("data: ") :]
        return json.loads(buf)

    def _setup_csv_writer(
        self, header=["msg_time", "update_time", "current", "z"]
    ) -> None:
        """Setup the CSV writer for logging lens updates."""
        file_path = os.path.join(self.save_folder, "lens_controller.csv")
        file_exists = os.path.isfile(file_path)
        self.csv_file = open(file_path, "a+", newline="")

        self.csv_file.seek(0)
        reader = csv.reader(self.csv_file)
        rows = list(reader)

        self.csv_writer = csv.writer(self.csv_file)
        if not file_exists or not rows or not rows[0]:
            self.csv_writer.writerow(header)

    def _write_row(self, row: list) -> None:
        """Write a row to the CSV file."""
        if self.csv_writer:
            self.csv_writer.writerow(row)

    def is_within_predefined_zone(self, data: Optional[Dict[str, float]]) -> bool:
        """Check if the object is within the predefined zone."""
        if data is None:
            return False
        return all(
            self.bounds[key][0] <= data[key] <= self.bounds[key][1]
            for key in ["x", "y", "z"]
        )

    def run(self) -> None:
        """Main loop for processing incoming data and controlling the lens."""
        try:
            for chunk in self.r.iter_content(chunk_size=None, decode_unicode=True):
                incoming_full = self._parse_chunk(chunk)
                self.tcall = time.time()

                try:
                    incoming = incoming_full["msg"]
                    self.detection_ts = incoming_full["trigger_timestamp"]
                except KeyError:
                    continue

                for msg_type in ["Birth", "Update", "Death"]:
                    if msg_type in incoming:
                        data = None if msg_type == "Death" else incoming[msg_type]
                        incoming_object = (
                            incoming[msg_type]
                            if msg_type == "Death"
                            else data["obj_id"]
                        )

                        in_zone = self.is_within_predefined_zone(data)

                        if self.current_tracked_object is None and in_zone:
                            self.start_tracking(incoming_object, data)
                        elif self.current_tracked_object == incoming_object:
                            if msg_type == "Death" or not in_zone:
                                self.stop_tracking()
                            elif in_zone:
                                self.update_lens(data["z"])

                        break

        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt. Exiting...")
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        finally:
            self.close()

    def start_tracking(self, incoming_object: str, data: Dict[str, float]) -> None:
        """Start tracking a new object."""
        logger.info(f"Started tracking object {incoming_object}")
        self.tracking_start_time = time.time()
        self.current_tracked_object = incoming_object
        self.update_lens(data["z"])

    def update_lens(self, z: float) -> None:
        """Update the lens focal power based on the object's z-position."""
        if time.time() - self.last_update < LENS_RESPONSE_TIME:
            return

        dpt = self.model.predict([[z]])[0]
        self._set_focalpower(dpt)
        self._write_row([time.time(), self.tcall, dpt, z])
        logger.debug(
            f"dt between detection and update {np.abs(time.time() - self.detection_ts)}"
        )
        self.last_update = time.time()

    def stop_tracking(self) -> None:
        """Stop tracking the current object."""
        logger.info(
            f"Stopped tracking object {self.current_tracked_object} after {(time.time() - self.tracking_start_time):.2f} seconds"
        )
        self.current_tracked_object = None
        self._soft_close()

    def _soft_close(self) -> None:
        """Gradually set the lens to 0 DPT."""
        current_dpt = self.device.get_diopter()
        for dpt in np.linspace(current_dpt, 0, 10):
            self.device.set_diopter(dpt)
            time.sleep(0.2)

    def close(self) -> None:
        """Close the liquid lens controller and cleanup resources."""
        logger.info("Closing device.")
        self._soft_close()
        if self.csv_file:
            self.csv_file.close()
        if self.session:
            self.session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--device_address",
        type=str,
        default="/dev/optotune_ld",
        help="The address of the liquid lens controller",
    )
    parser.add_argument("--braidz_url", type=str, default="http://10.40.80.6:8397/")
    parser.add_argument(
        "--params_file",
        type=str,
        default="/home/buchsbaum/src/BraidTrigger/params.toml",
    )
    parser.add_argument("--save_folder", type=str, default="")
    args = parser.parse_args()

    lens = LensController(
        device_address=args.device_address,
        braidz_url=args.braidz_url,
        params_file=args.params_file,
        save_folder=args.save_folder,
    )

    logger.info("Starting liquid lens controller.")
    lens.run()
