# hardware_utils.py
import serial

from modules.utils.rspowersupply import PowerSupply


def initialize_backlighting_power_supply(port="/dev/powersupply", voltage=30):
    """
    Initializes the backlighting power supply.

    Args:
        port (str, optional): The port of the power supply. Defaults to "/dev/powersupply".
        voltage (int, optional): The voltage to set on the power supply. Defaults to 30.

    Raises:
        RuntimeError: If the backlight power supply is not connected.
    """
    try:
        ps = PowerSupply(port=port)
        ps.set_voltage(voltage)
        return ps
    except RuntimeError:
        raise RuntimeError("Backlight power supply not connected.")


def create_arduino_device(port: str, baudrate: int = 9600) -> serial.Serial:
    """
    Creates an Arduino device object.

    Args:
        port (str): The port to which the Arduino device is connected.
        baudrate (int, optional): The baud rate for communication. Defaults to 9600.

    Returns:
        serial.Serial: The Arduino device object.

    """
    return serial.Serial(port, baudrate=baudrate, timeout=1)
