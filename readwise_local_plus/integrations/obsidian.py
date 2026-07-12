import logging
from typing import Any
from readwise_local_plus.config import UserConfig

from pathlib import Path


REQUIRED_PARENT_FOLDERS = ["podcasts"]


logger = logging.getLogger(__name__)


def ensure_rw_parent_folders(
        user_config: UserConfig, required_folders: list[int] = REQUIRED_PARENT_FOLDERS
    ) -> None:
    for required_folder in REQUIRED_PARENT_FOLDERS:
        expected_path = user_config.obsidian_vault_path / required_folder
        if not expected_path.is_dir():
            expected_path.mkdir() # Error if exists, or parents don't exist
            logger.info(f"Created required folder: {expected_path}")


def obsidian_experiment(user_config: UserConfig, batch_id: int):
    print("Hello Obsidian Export!")
    # obs_root_dirs = get_dirs(user_config.obsidian_vault_path)
    ensure_rw_parent_folders(user_config)


