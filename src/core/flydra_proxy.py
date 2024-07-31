import asyncio
import aiohttp
import json
from typing import AsyncGenerator, Dict, Optional
from src.utils.log_config import setup_logging

logger = setup_logging(logger_name="AsyncFlydra2Proxy", level="INFO")


class AsyncFlydra2Proxy:
    def __init__(self, flydra2_url: str = "http://10.40.80.6:8397/"):
        self.flydra2_url = flydra2_url
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        await self._connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _connect(self) -> None:
        if not self.session:
            raise RuntimeError(
                "Session not initialized. Use AsyncFlydra2Proxy as a context manager."
            )
        try:
            async with self.session.get(self.flydra2_url) as response:
                response.raise_for_status()
            logger.info(
                f"Successfully connected to Flydra2 server at {self.flydra2_url}"
            )
        except aiohttp.ClientError as e:
            logger.error(f"Failed to connect to Flydra2 server: {e}")
            raise ConnectionError(f"Unable to connect to Flydra2 server: {e}") from e

    async def data_stream(self) -> AsyncGenerator[Dict, None]:
        if not self.session:
            raise RuntimeError(
                "Session not initialized. Use AsyncFlydra2Proxy as a context manager."
            )
        events_url = f"{self.flydra2_url}events"
        try:
            async with self.session.get(
                events_url, headers={"Accept": "text/event-stream"}
            ) as response:
                response.raise_for_status()
                logger.info("Started data stream from Flydra2 server")
                async for chunk in response.content:
                    data = await self._parse_chunk(chunk.decode("utf-8"))
                    if data:
                        yield data
        except aiohttp.ClientError as e:
            logger.error(f"Failed to get events stream from Flydra2 server: {e}")
            raise ConnectionError(f"Unable to start data stream: {e}") from e

    async def _parse_chunk(self, chunk: str) -> Optional[Dict]:
        DATA_PREFIX = "data: "
        lines = chunk.strip().split("\n")
        if (
            len(lines) != 2
            or lines[0] != "event: braid"
            or not lines[1].startswith(DATA_PREFIX)
        ):
            logger.warning(f"Unexpected chunk format: {chunk}")
            return None

        buf = lines[1][len(DATA_PREFIX) :]
        try:
            data = json.loads(buf)
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON data: {e}")
            return None

    async def send_to_udp(self, udp_host: str, udp_port: int) -> None:
        addr = (udp_host, udp_port)
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: asyncio.DatagramProtocol(), remote_addr=addr
        )

        try:
            logger.info(f"Starting UDP transmission to {udp_host}:{udp_port}")
            async for data in self.data_stream():
                version = data.get("v", 1)
                if version != 2:
                    logger.warning(f"Unexpected version: {version}")
                    continue

                try:
                    update_dict = data["msg"]["Update"]
                    msg = f"{update_dict['x']}, {update_dict['y']}, {update_dict['z']}"
                    transport.sendto(msg.encode("ascii"))
                except KeyError:
                    logger.warning("Missing 'Update' key in data message")
                except Exception as e:
                    logger.error(f"Error sending UDP data: {e}")
        finally:
            transport.close()


async def main():
    async with AsyncFlydra2Proxy() as proxy:
        try:
            async for data in proxy.data_stream():
                print(data)
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Data stream interrupted by user")
        except Exception as e:
            logger.error(f"An error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(main())
