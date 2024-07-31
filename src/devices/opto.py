import random
from typing import Tuple, Dict, Any, Optional
import serial

from src.utils.log_config import setup_logging
from src.utils.serial_utils import create_serial_connection, send_message

logger = setup_logging(logger_name="Opto", level="INFO")


class OptoTrigger:
    def __init__(self, port: str, baudrate: int, params: Dict[str, Any]):
        self.port = port
        self.baudrate = baudrate
        self.params = params
        self.device: Optional[serial.Serial] = None

    def connect(self) -> None:
        """Establish connection to the device."""
        try:
            self.device = create_serial_connection(self.port, self.baudrate)
            logger.info(f"Connected to OptoTrigger device on port {self.port}")
        except ConnectionError as e:
            logger.error(f"Failed to connect to OptoTrigger device: {e}")
            raise

    def close(self) -> None:
        """Close the connection to the device."""
        if self.device:
            self.device.close()
            logger.info("Closed connection to OptoTrigger device")
        self.device = None

    def get_trigger_parameters(self) -> Tuple[float, float, float]:
        """Get the opto trigger parameters based on the given params."""
        if random.random() < self.params.get("sham_perc", 0):
            logger.debug("Sham opto triggered.")
            return 0, 0, 0

        return (
            self.params.get("duration", 0),
            self.params.get("intensity", 0),
            self.params.get("frequency", 0),
        )

    def trigger(self) -> Tuple[float, float, float]:
        """Trigger the opto stimulus and return the parameters used."""
        if not self.device:
            raise RuntimeError("Device not connected. Call connect() first.")

        stim_duration, stim_intensity, stim_frequency = self.get_trigger_parameters()
        message = f"<{stim_duration},{stim_intensity},{stim_frequency}>"

        try:
            send_message(self.device, message)
            logger.info(
                f"Triggered opto with duration: {stim_duration}, intensity: {stim_intensity}, frequency: {stim_frequency}"
            )
        except ConnectionError as e:
            logger.error(f"Failed to trigger opto: {e}")
            raise

        return stim_duration, stim_intensity, stim_frequency

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
