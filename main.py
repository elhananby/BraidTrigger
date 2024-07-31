import argparse
import asyncio
import os
from typing import Dict, Any

import tomllib
from contextlib import AsyncExitStack

from src.core.flydra_proxy import AsyncFlydra2Proxy
from src.core.publisher import AsyncPublisher
from src.utils.csv_writer import CsvWriter
from src.utils.file_operations import (
    check_braid_running,
    copy_files_to_folder,
    get_video_output_folder,
)
from src.devices.powersupply import initialize_backlighting_power_supply
from src.utils.log_config import setup_logging
from src.devices.opto import OptoTrigger
from src.processing.data_processor import (
    DataProcessor,
    TrajectoryData,
    TriggerConfig,
    OptoConfig,
)
from src.processing.trajectory import RealTimeHeadingCalculator
from src.devices.cameras.ximea_camera import XimeaCamera

logger = setup_logging(logger_name="Main", level="INFO")

ROOT_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
PARAMS_FILE = os.path.join(ROOT_DIR, "params.toml")
ROOT_FOLDER = "/home/buchsbaum/mnt/DATA/Experiments/"
VOLTAGE = 23.5


async def start_ximea_camera(params: Dict[str, Any], braid_folder: str):
    video_save_folder = get_video_output_folder(braid_folder)
    camera_params = params["highspeed"]["parameters"]
    return await XimeaCamera.create(
        save_folder=video_save_folder,
        fps=camera_params["fps"],
        exposure_time=camera_params["exposure_time"],
        pre_trigger_mode=camera_params["pre_trigger_mode"],
        time_before=camera_params["time_before"],
        time_after=camera_params["time_after"],
        sensor_readout_mode=camera_params["sensor_readout_mode"],
    )


async def start_liquid_lens(params: Dict[str, Any], braid_folder: str):
    return await asyncio.create_subprocess_exec(
        "libs/lens_controller/target/release/lens_controller",
        "--braid-url",
        "http://10.40.80.6:8397/",
        "--lens-driver-port",
        params["arduino_devices"]["liquid_lens"],
        "--update-interval-ms",
        "20",
        "--save-folder",
        braid_folder,
    )


async def start_visual_stimuli(params: Dict[str, Any], braid_folder: str):
    return await asyncio.create_subprocess_exec(
        "python",
        os.path.join(ROOT_DIR, "src", "visualization", "visual_stimuli.py"),
        PARAMS_FILE,
        "--base_dir",
        braid_folder,
    )


async def process_flydra_data(
    proxy: AsyncFlydra2Proxy,
    data_processor: DataProcessor,
    trajectory_data: TrajectoryData,
    trigger_config: TriggerConfig,
    opto_config: OptoConfig,
    max_runtime: float,
):
    start_time = asyncio.get_event_loop().time()
    try:
        async for data in proxy.data_stream():
            current_time = asyncio.get_event_loop().time()
            if (current_time - start_time) >= max_runtime:
                break

            try:
                msg_dict = data["msg"]
            except KeyError:
                continue

            if "Birth" in msg_dict:
                curr_obj_id = msg_dict["Birth"]["obj_id"]
                trajectory_data.obj_ids.append(curr_obj_id)
                trajectory_data.birth_times[curr_obj_id] = current_time
                trajectory_data.headings[curr_obj_id] = RealTimeHeadingCalculator()
            elif "Update" in msg_dict:
                await data_processor.handle_update(
                    msg_dict, trajectory_data, trigger_config, opto_config
                )
            elif "Death" in msg_dict:
                curr_obj_id = msg_dict["Death"]
                if curr_obj_id in trajectory_data.obj_ids:
                    trajectory_data.obj_ids.remove(curr_obj_id)

    except asyncio.CancelledError:
        logger.info("Flydra data processing cancelled")
    except Exception as e:
        logger.error(f"Error in Flydra data processing: {e}")


async def main(params_file: str, root_folder: str, args: argparse.Namespace):
    with open(params_file, "rb") as f:
        params = tomllib.load(f)

    braid_folder = check_braid_running(root_folder, args.debug)
    params["folder"] = braid_folder
    copy_files_to_folder(braid_folder, params_file)

    power_supply = initialize_backlighting_power_supply(
        port=params["arduino_devices"]["power_supply"]
    )
    power_supply.set_voltage(29)

    async with AsyncExitStack() as stack:
        try:
            flydra_proxy = await stack.enter_async_context(AsyncFlydra2Proxy())
            publisher = await stack.enter_async_context(
                AsyncPublisher(pub_port=5556, handshake_port=5557)
            )

            csv_writer = CsvWriter(os.path.join(braid_folder, "opto.csv"))
            await stack.enter_async_context(csv_writer)

            data_processor = DataProcessor(publisher, csv_writer)
            trajectory_data = TrajectoryData([], {}, {})
            trigger_config = TriggerConfig(params["trigger_params"], 0, 0)

            if params["opto_params"]["active"]:
                opto_trigger = OptoTrigger(
                    params["arduino_devices"]["opto_trigger"],
                    9600,
                    params["opto_params"],
                )
                await stack.enter_async_context(opto_trigger)
                opto_config = OptoConfig(params["opto_params"], opto_trigger)
            else:
                opto_config = OptoConfig(params["opto_params"], None)

            child_processes = {}
            if params["highspeed"]["active"]:
                child_processes["ximea_camera"] = await start_ximea_camera(
                    params, braid_folder
                )
                child_processes["liquid_lens"] = await start_liquid_lens(
                    params, braid_folder
                )

            if any(
                params["stim_params"][stim].get("active", False)
                for stim in params["stim_params"]
                if stim != "window"
            ):
                child_processes["visual_stimuli"] = await start_visual_stimuli(
                    params, braid_folder
                )

            flydra_task = asyncio.create_task(
                process_flydra_data(
                    flydra_proxy,
                    data_processor,
                    trajectory_data,
                    trigger_config,
                    opto_config,
                    params["max_runtime"] * 3600,
                )
            )

            try:
                await flydra_task
            except asyncio.TimeoutError:
                logger.info(
                    f"Maximum runtime of {params['max_runtime']} hours reached."
                )
            finally:
                await publisher.publish("trigger", "kill")
                await publisher.publish("lens", "kill")

                for process in child_processes.values():
                    if isinstance(process, asyncio.subprocess.Process):
                        process.terminate()
                        await process.wait()
                    else:
                        await process.stop()

        except Exception as e:
            logger.error(f"An error occurred: {e}")
        finally:
            power_supply.set_voltage(0)
            power_supply.close()

    logger.info("Main function completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument("--plot", action="store_true", default=False)
    args = parser.parse_args()

    logger.info("Starting main function.")
    asyncio.run(main(PARAMS_FILE, ROOT_FOLDER, args))
