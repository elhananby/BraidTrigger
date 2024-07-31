import filecmp
import os
import pathlib
import shutil
import time

import git
from tqdm.contrib.concurrent import thread_map

from src.utils.log_config import setup_logging

logger = setup_logging(logger_name="Files", level="INFO", color="green")


def check_braid_folder(root_folder: str) -> str:
    """
    Check if a .braid folder exists in the specified root folder.
    If the folder does not exist, wait until it is created.

    Args:
        root_folder (str): The root folder to check for the .braid folder.

    Returns:
        str: The path of the first .braid folder found.
    """
    p = pathlib.Path(root_folder)
    curr_braid_folder = list(p.glob("*.braid"))

    if len(curr_braid_folder) == 0:
        logger.info(f"Waiting for .braid folder to be created in {root_folder}....")

    while len(curr_braid_folder) == 0:
        time.sleep(1)
        p = pathlib.Path(root_folder)
        curr_braid_folder = list(p.glob("*.braid"))

    logger.info(f"\nFolder {curr_braid_folder[0].as_posix()} found.")

    return curr_braid_folder[0].as_posix()


def check_braid_running(root_folder: str, debug: bool) -> str:
    if not debug:
        return check_braid_folder(root_folder)
    else:
        os.makedirs("test/", exist_ok=True)
        return "test/"


def copy_files_with_progress(src_folder, dest_folder):
    """
    Copy files from the source folder to the destination folder with progress.

    Args:
        src_folder (str): The path to the source folder.
        dest_folder (str): The path to the destination folder.

    Returns:
        None
    """

    def copy_file(src_file_path, dest_file_path):
        shutil.copy2(src_file_path, dest_file_path)

        if filecmp.cmp(src_file_path, dest_file_path, shallow=False):
            logger.debug(f"File {src_file_path} copied successfully.")
            os.remove(src_file_path)

    files = [
        f for f in os.listdir(src_folder) if os.path.isfile(os.path.join(src_folder, f))
    ]
    src_file_paths = [os.path.join(src_folder, file) for file in files]
    dest_file_paths = [os.path.join(dest_folder, file) for file in files]

    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    thread_map(copy_file, src_file_paths, dest_file_paths, max_workers=4)

    if len(os.listdir(src_folder)) == 0:
        os.rmdir(src_folder)


def copy_files_to_folder(folder: str, file: str):
    """
    Copy a file to a specified folder and write the commit hash to a params.toml file.

    Args:
        folder (str): The destination folder where the file will be copied to.
        file (str): The path of the file to be copied.

    Returns:
        None
    """
    shutil.copy(file, folder)
    with open(os.path.join(folder, "params.toml"), "a+") as f:
        f.write(
            f"commit = {git.Repo(search_parent_directories=True).head.commit.hexsha}"
        )


def get_video_output_folder(
    braid_folder: str, base_folder: str = "/home/buchsbaum/mnt/DATA/Videos/"
):
    """
    Get the output folder path for a video based on the braid folder.

    Args:
        braid_folder (str): The path of the braid folder.
        base_folder (str, optional): The base folder where the video output folder will be created. Defaults to "/home/buchsbaum/mnt/DATA/Videos/".

    Returns:
        str: The output folder path for the video.
    """

    braid_folder = os.path.splitext(os.path.basename(braid_folder))[0]
    return os.path.join(base_folder, braid_folder)
