import serial
from typing import Any


def create_serial_connection(
    port: str, baudrate: int = 9600, timeout: float = 1.0
) -> serial.Serial:
    """Create a serial connection."""
    try:
        return serial.Serial(port, baudrate=baudrate, timeout=timeout)
    except serial.SerialException as e:
        raise ConnectionError(f"Failed to connect to port {port}: {e}")


def send_message(connection: serial.Serial, message: str) -> None:
    """Send a message over the serial connection."""
    try:
        connection.write(message.encode())
    except serial.SerialException as e:
        raise ConnectionError(f"Failed to send message: {e}")


def receive_message(connection: serial.Serial, size: int = 1024) -> str:
    """Receive a message from the serial connection."""
    try:
        return connection.read(size).decode()
    except serial.SerialException as e:
        raise ConnectionError(f"Failed to receive message: {e}")


def parse_message(message: str) -> Any:
    """Parse the received message. Implement your parsing logic here."""
    # This is a placeholder. Implement your actual parsing logic.
    return message.strip()
