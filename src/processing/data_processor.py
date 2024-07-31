from dataclasses import dataclass
from typing import Dict, List, Any
import time
import json

from src.core.publisher import AsyncPublisher
from src.utils.csv_writer import CsvWriter
from src.processing.trajectory import RealTimeHeadingCalculator, check_position
from src.devices.opto import OptoTrigger
from src.utils.log_config import setup_logging

logger = setup_logging(logger_name="DataProcessor", level="INFO")


@dataclass
class TrajectoryData:
    obj_ids: List[str]
    birth_times: Dict[str, float]
    headings: Dict[str, RealTimeHeadingCalculator]


@dataclass
class TriggerConfig:
    params: Dict[str, Any]
    last_trigger_time: float
    ntrig: int


@dataclass
class OptoConfig:
    params: Dict[str, Any]
    trigger: OptoTrigger


class DataProcessor:
    def __init__(self, publisher: AsyncPublisher, csv_writer: CsvWriter):
        self.publisher = publisher
        self.csv_writer = csv_writer

    async def handle_update(
        self,
        msg_dict: Dict[str, Any],
        trajectory_data: TrajectoryData,
        trigger_config: TriggerConfig,
        opto_config: OptoConfig,
    ):
        curr_obj_id = msg_dict["Update"]["obj_id"]
        current_time = time.time()

        if not self._should_process_update(
            curr_obj_id, current_time, trajectory_data, trigger_config, msg_dict
        ):
            return

        pos = msg_dict["Update"]
        if check_position(pos, trigger_config.params):
            await self._process_trigger(
                pos,
                curr_obj_id,
                current_time,
                trajectory_data,
                trigger_config,
                opto_config,
            )

    def _should_process_update(
        self,
        curr_obj_id: str,
        current_time: float,
        trajectory_data: TrajectoryData,
        trigger_config: TriggerConfig,
        msg_dict: Dict[str, Any],
    ) -> bool:
        if curr_obj_id not in trajectory_data.headings:
            trajectory_data.headings[curr_obj_id] = RealTimeHeadingCalculator()

        trajectory_data.headings[curr_obj_id].add_data_point(
            msg_dict["Update"]["xvel"],
            msg_dict["Update"]["yvel"],
            msg_dict["Update"]["zvel"],
        )

        if curr_obj_id not in trajectory_data.obj_ids:
            trajectory_data.obj_ids.append(curr_obj_id)
            trajectory_data.birth_times[curr_obj_id] = current_time
            return False

        if (
            current_time - trajectory_data.birth_times[curr_obj_id]
        ) < trigger_config.params["min_trajectory_time"]:
            return False

        if (
            current_time - trigger_config.last_trigger_time
            < trigger_config.params["min_trigger_interval"]
        ):
            return False

        return True

    async def _process_trigger(
        self,
        pos: Dict[str, Any],
        curr_obj_id: str,
        current_time: float,
        trajectory_data: TrajectoryData,
        trigger_config: TriggerConfig,
        opto_config: OptoConfig,
    ):
        trigger_config.ntrig += 1
        trigger_config.last_trigger_time = current_time

        pos.update(
            {
                "trigger_time": current_time,
                "ntrig": trigger_config.ntrig,
                "main_timestamp": current_time,
                "heading_direction": trajectory_data.headings[
                    curr_obj_id
                ].calculate_heading(),
            }
        )

        if opto_config.params.get("active", False):
            logger.info("Triggering opto.")
            stim_duration, stim_intensity, stim_frequency = (
                opto_config.trigger.trigger()
            )
            pos.update(
                {
                    "stim_duration": stim_duration,
                    "stim_intensity": stim_intensity,
                    "stim_frequency": stim_frequency,
                }
            )

        logger.debug(f"Publishing message to 'trigger': {pos}")
        await self.publisher.publish(json.dumps(pos), "trigger")
        self.csv_writer.write(pos)
