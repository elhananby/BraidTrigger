import argparse
import json
import os
import random
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from enum import Enum, auto
from dataclasses import dataclass

import numpy as np
import pygame
import toml
import asyncio

from src.utils.csv_writer import CsvWriter
from src.utils.log_config import setup_logging
from src.core.subscriber import AsyncSubscriber

logger = setup_logging(logger_name="VisualStimuli", level="INFO", color="yellow")

# Constants
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 128
os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"


class StimulusType(Enum):
    STATIC = auto()
    LOOMING = auto()
    GRATING = auto()


@dataclass
class StimulusConfig:
    type: StimulusType
    active: bool
    color: str
    position: str
    max_radius: int
    duration: int
    frequency: float
    direction: str


class Stimulus(ABC):
    def __init__(self, config: StimulusConfig):
        self.config = config

    @abstractmethod
    def update(self, screen: pygame.Surface, time_elapsed: int) -> None:
        pass


class StaticImageStimulus(Stimulus):
    def __init__(self, config: StimulusConfig):
        super().__init__(config)
        self.image = pygame.image.load(config.image).convert()
        self.image = pygame.transform.scale(self.image, (SCREEN_WIDTH, SCREEN_HEIGHT))

    def update(self, screen: pygame.Surface, time_elapsed: int) -> None:
        screen.blit(self.image, (0, 0))


def wrap_around_position(x: float, screen_width: int) -> float:
    return x % screen_width


def interp_angle(angle: float) -> float:
    screen = [0, 128, 256, 384, 512]
    heading = [1.518, 2.776, -2.198, -0.978, 0.213]
    return np.interp(angle, heading, screen, period=2 * np.pi)


class LoomingStimulus(Stimulus):
    def __init__(self, config: StimulusConfig):
        super().__init__(config)
        self.max_radius = self._get_value(config.max_radius, 0, 100)
        self.duration = self._get_value(config.duration, 150, 500)
        self.color = pygame.Color(config.color)
        self.position_type = config.position
        self.position: Optional[float] = None
        self.start_time: Optional[float] = None
        self.expanding = False
        self.type = config.type

    def _get_value(self, value: Any, min_val: int, max_val: int) -> int:
        return random.randint(min_val, max_val) if value == "random" else int(value)

    def generate_natural_looming(
        self,
        max_radius: int,
        duration: int,
        l_v: float = 10,
        distance_from_screen: float = 25,
        hz: int = 60,
    ) -> np.ndarray:
        n_frames = int(duration / (1000 / hz))
        r = np.flip([2 * np.arctan(l_v / i) for i in range(1, n_frames)])
        looming_size_on_screen = np.tan(r / 2) * distance_from_screen
        looming_size_on_screen = (
            looming_size_on_screen - np.min(looming_size_on_screen)
        ) / (np.max(looming_size_on_screen) - np.min(looming_size_on_screen))
        return looming_size_on_screen * max_radius

    def start_expansion(self, heading_direction: Optional[float] = None) -> None:
        self.max_radius = self._get_value(self.config.max_radius, 32, 64)
        self.duration = self._get_value(self.config.duration, 150, 500)
        if self.position_type == "random":
            self.position = self._get_value("random", 0, SCREEN_WIDTH)
        elif self.position_type == "closed-loop":
            self.position = (
                interp_angle(heading_direction)
                if heading_direction is not None
                else self._get_value("random", 0, SCREEN_WIDTH)
            )
        else:
            self.position = float(self.position_type)

        if self.type == StimulusType.LOOMING:
            self.radii_array = self.generate_natural_looming(
                self.max_radius, self.duration
            )
        self.start_time = time.time()
        self.curr_frame = 0
        self.n_frames = int(self.duration / (1000 / 60))
        self.expanding = True

    def update(self, screen: pygame.Surface, time_elapsed: int) -> None:
        if self.expanding and self.curr_frame < self.n_frames - 1:
            self.radius = (
                self.radii_array[self.curr_frame]
                if self.type == StimulusType.LOOMING
                else (self.curr_frame / self.n_frames) * self.max_radius
            )
            assert self.position is not None
            position = wrap_around_position(self.position, SCREEN_WIDTH)
            pygame.draw.circle(
                screen,
                self.color,
                (int(position), SCREEN_HEIGHT // 2),
                int(self.radius),
            )
            if position - self.radius < 0:
                pygame.draw.circle(
                    screen,
                    self.color,
                    (int(position + SCREEN_WIDTH), SCREEN_HEIGHT // 2),
                    int(self.radius),
                )
            if position + self.radius > SCREEN_WIDTH:
                pygame.draw.circle(
                    screen,
                    self.color,
                    (int(position - SCREEN_WIDTH), SCREEN_HEIGHT // 2),
                    int(self.radius),
                )
            self.curr_frame += 1
        else:
            self.expanding = False

    def get_trigger_info(self) -> Dict[str, Any]:
        return {
            "timestamp": time.time(),
            "stimulus": self.type.name,
            "expansion": self.expanding,
            "max_radius": self.max_radius,
            "duration": self.duration,
            "color": self.color,
            "position": self.position,
        }


class GratingStimulus(Stimulus):
    def __init__(self, config: StimulusConfig):
        super().__init__(config)
        self.frequency = config.frequency
        self.direction = config.direction
        self.color = pygame.Color(config.color)

    def update(self, screen: pygame.Surface, time_elapsed: int) -> None:
        pass


async def connect_to_zmq(
    pub_port: int = 5556, handshake_port: int = 5557
) -> AsyncSubscriber:
    try:
        subscriber = AsyncSubscriber(pub_port, handshake_port)
        await subscriber.setup()
        await subscriber.handshake()
        logger.debug("Handshake successful")
        subscriber.subscribe("trigger")
        logger.debug("Subscribed to `trigger` messages")
        return subscriber
    except Exception as e:
        logger.error(f"Failed to connect to ZMQ: {e}")
        raise


def create_stimuli(config: Dict[str, Any]) -> List[Stimulus]:
    stim_config = config["stim_params"]
    stimuli = []
    stimulus_classes = {
        StimulusType.STATIC: StaticImageStimulus,
        StimulusType.LOOMING: LoomingStimulus,
        StimulusType.GRATING: GratingStimulus,
    }

    for stim_type, StimulusClass in stimulus_classes.items():
        if stim_config[stim_type.name.lower()].get("active", False):
            config = StimulusConfig(
                type=stim_type, **stim_config[stim_type.name.lower()]
            )
            stimuli.append(StimulusClass(config))

    return stimuli


async def main_loop(
    screen: pygame.Surface,
    stimuli: List[Stimulus],
    subscriber: AsyncSubscriber,
    csv_writer: Optional[CsvWriter],
    standalone: bool,
):
    clock = pygame.time.Clock()
    running = True
    while running:
        time_elapsed = clock.get_time()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_k:
                logger.info("Key pressed: K")
                for stim in stimuli:
                    if isinstance(stim, LoomingStimulus):
                        stim.start_expansion()

        if not standalone:
            try:
                topic, message = await subscriber.receive()
                if message == "kill":
                    logger.info("Received kill message. Exiting...")
                    running = False
                elif message:
                    trigger_info = json.loads(message)
                    heading_direction = trigger_info.get("heading_direction")
                    logger.info("Triggering stimulus")
                    logger.debug(f"Got heading direction: {heading_direction}")

                    for stim in stimuli:
                        if isinstance(stim, LoomingStimulus):
                            stim.start_expansion(heading_direction)
                            updated_info = stim.get_trigger_info()
                            trigger_info.update(updated_info)
                            if csv_writer:
                                csv_writer.write(trigger_info)
            except json.JSONDecodeError as e:
                logger.error(f"JSON Decode Error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error while receiving message: {e}")

        screen.fill((255, 255, 255))
        for stim in stimuli:
            stim.update(screen, time_elapsed)

        pygame.display.flip()
        await asyncio.sleep(1 / 60)  # 60 FPS


async def main(config_file: str, base_dir: str, standalone: bool) -> None:
    pygame.init()
    try:
        with open(config_file, "r") as f:
            config = toml.load(f)

        stimuli = create_stimuli(config)

        if not standalone:
            csv_writer = CsvWriter(os.path.join(base_dir, "stim.csv"))
            subscriber = await connect_to_zmq()
        else:
            csv_writer = None
            subscriber = None

        screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.NOFRAME)
        pygame.display.set_caption("Stimulus Display")

        await main_loop(screen, stimuli, subscriber, csv_writer, standalone)

    except Exception as e:
        logger.error(f"An error occurred: {e}")
    finally:
        if not standalone and csv_writer:
            csv_writer.close()
        if subscriber:
            await subscriber.close()
        pygame.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stimulus Display Program")
    parser.add_argument(
        "config_file", type=str, help="Path to the configuration file (.toml)"
    )
    parser.add_argument(
        "--base_dir",
        type=str,
        required=False,
        default="",
        help="Base directory to save stim.csv",
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        default=False,
        help="Run the program in standalone mode without ZMQ",
    )
    args = parser.parse_args()

    asyncio.run(main(args.config_file, args.base_dir, args.standalone))
