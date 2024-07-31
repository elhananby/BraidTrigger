import zmq
import asyncio
from src.utils.log_config import setup_logging

logger = setup_logging(logger_name="Subscriber", level="INFO", color="cyan")


class AsyncSubscriber:
    def __init__(
        self,
        pub_port: int,
        handshake_port: int,
        server_address: str = "localhost",
        max_retry_attempts: int = 5,
        retry_interval: float = 5.0,
    ):
        self.context = zmq.asyncio.Context()
        self.pub_port = pub_port
        self.handshake_port = handshake_port
        self.server_address = server_address
        self.max_retry_attempts = max_retry_attempts
        self.retry_interval = retry_interval
        self.sub_socket = None
        self.req_socket = None

    async def __aenter__(self):
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def setup(self):
        self.sub_socket = self.context.socket(zmq.SUB)
        self.sub_socket.connect(f"tcp://{self.server_address}:{self.pub_port}")

        self.req_socket = self.context.socket(zmq.REQ)
        self.req_socket.connect(f"tcp://{self.server_address}:{self.handshake_port}")

    async def handshake(self) -> bool:
        for attempt in range(self.max_retry_attempts):
            try:
                await self.req_socket.send_string("Hello")
                reply = await self.req_socket.recv_string()
                if reply == "Welcome":
                    logger.info("Handshake successful.")
                    return True
                else:
                    logger.warning(f"Handshake failed. Unexpected reply: {reply}")
            except zmq.ZMQError as e:
                logger.error(f"Handshake error: {e}")

            if attempt < self.max_retry_attempts - 1:
                logger.info(f"Retrying handshake in {self.retry_interval} seconds...")
                await asyncio.sleep(self.retry_interval)

        logger.error("Handshake failed after maximum retry attempts.")
        return False

    def subscribe(self, topic: str = ""):
        try:
            self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, topic)
            logger.info(f"Subscribed to topic '{topic}'.")
        except zmq.ZMQError as e:
            logger.error(f"Failed to subscribe to topic '{topic}': {e}")

    async def receive(self):
        try:
            message = await self.sub_socket.recv_string()
            topic, actual_message = message.split(" ", 1)
            logger.debug(f"Received message: {message}")
            return topic, actual_message
        except ValueError as e:
            logger.error(f"Error parsing message: {e}")
        except zmq.ZMQError as e:
            logger.error(f"ZMQ error while receiving message: {e}")
        except Exception as e:
            logger.error(f"Unexpected error while receiving message: {e}")
        return None, None

    async def close(self):
        if self.sub_socket:
            self.sub_socket.close()
        if self.req_socket:
            self.req_socket.close()
        self.context.term()
        logger.info("Closed subscriber sockets and terminated context.")


# Example usage
async def subscriber_example():
    async with AsyncSubscriber(pub_port=5556, handshake_port=5557) as sub:
        await sub.handshake()
        sub.subscribe("topic")
        for _ in range(5):
            topic, message = await sub.receive()
            if topic and message:
                print(f"Received: {topic} - {message}")


if __name__ == "__main__":
    asyncio.run(subscriber_example())
