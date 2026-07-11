import logging
from typing import Any
from readwise_local_plus.config import UserConfig

from pathlib import Path


def get_dirs(target_path: Path) -> str:
    paths = target_path.iterdir()
    
    dirs = []
    for path in paths:
        if path.is_dir():
            dirs.append(path)

    print("--- Dirs only ---")
    for dir in dirs:
        print(dir)


def obsidian_experiment(user_config: UserConfig, batch_id: int):
    print("Hello Obsidian Export!")
    print("Batch ID is ", batch_id)
    print("---")
    print(user_config)
    print("---")
    get_dirs(user_config.obsidian_vault_path)


