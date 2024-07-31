import zmq
import asyncio
from src.utils.log_config import setup_logging

logger = setup_logging(logger_name="Publisher", level="INFO", color="cyan")


class AsyncPublisher:
    def __init__(self, pub_port: int, handshake_port: int):
        self.context = zmq.asyncio.Context()
        self.pub_port = pub_port
        self.handshake_port = handshake_port
        self.pub_socket = None
        self.rep_socket = None

    async def __aenter__(self):
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def setup(self):
        self.pub_socket = self.context.socket(zmq.PUB)
        self.pub_socket.bind(f"tcp://*:{self.pub_port}")

        self.rep_socket = self.context.socket(zmq.REP)
        self.rep_socket.bind(f"tcp://*:{self.handshake_port}")

    async def wait_for_subscriber(self):
        try:
            message = await self.rep_socket.recv_string(flags=zmq.NOBLOCK)
            if message == "Hello":
                await self.rep_socket.send_string("Welcome")
                logger.info("Handshake completed with a subscriber.")
        except zmq.Again:
            logger.warning("No handshake request received yet.")
        except zmq.ZMQError as e:
            logger.error(f"ZMQ Error during handshake: {e}")

    async def publish(self, msg: str, topic: str = ""):
        try:
            await self.pub_socket.send_string(f"{topic} {msg}")
            logger.debug(f"Published message on topic '{topic}': {msg}")
        except zmq.ZMQError as e:
            logger.error(f"Failed to publish message: {e}")

    async def close(self):
        if self.pub_socket:
            self.pub_socket.close()
        if self.rep_socket:
            self.rep_socket.close()
        self.context.term()
        logger.info("Closed publisher sockets and terminated context.")


# Example usage
async def publisher_example():
    async with AsyncPublisher(pub_port=5556, handshake_port=5557) as pub:
        await pub.wait_for_subscriber()
        for i in range(5):
            await pub.publish(f"Message {i}", "topic")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(publisher_example())
