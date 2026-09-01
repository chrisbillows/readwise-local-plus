from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date
import logging
from typing import Any
import os
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from pathlib import Path

from readwise_local_plus.config import UserConfig, fetch_user_config
from readwise_local_plus.db_operations import get_session
from readwise_local_plus.db_export import (
        BookFromDb, HighlightFromDb, SnipdEpisodeFromDb, DbHls
    )
from readwise_local_plus.models import (
    Book, Highlight,
)


logger = logging.getLogger(__name__)


REQUIRED_CATEGORY_DIRS = ["podcasts"]
# key is rw name, value is desired name

PODCAST_TITLE_MAP = {
    "The Rest Is History": "Rest Is History",
    "The Rest Is Politics": "Rest Is Politics",
}


def ensure_dir_exists(dir_path: Path, parents: bool = False) -> None:
    if not dir_path.is_dir():
        dir_path.mkdir(parents=parents) # Error if exists, or parents don't exist
        logger.info(f"Created dir: {dir_path}")


def ensure_readwise_dirs(
        user_config: UserConfig, category_dirs: list[int] = REQUIRED_CATEGORY_DIRS
    ) -> None:
    """
    Create Readwise and category dirs, if not present.
    """
    # This will create the Readwise dir if it doesn't exist also.
    for category_folder in category_dirs:
        expected_path = user_config.obsidian_rw_dir / category_folder
        ensure_dir_exists(expected_path, True)        



def write_batch_to_obsidian(user_config: UserConfig, batch_id: int):
    """Entry point function to write a batch of highlights to Obsidian."""
    ensure_readwise_dirs(user_config)

    db_hls = DbHls("all_snipd")
    db_hls.populate()

    # TODOs: Use analysis obj if still needed
    # print_highlight_type_stats(batch_hls_by_book)

    for snipd_ep in db_hls.hls_by_snipd_url:

        snipd_ep.populate()

        if not snipd_ep.full_page:
            print("UH OH NO FULL PAGE BRO..")

        else:
            # `podcasts` aka BookFromDb.category is hardcoded for consistency
            podcast_dir = user_config.obsidian_rw_dir / "podcasts" / snipd_ep.podcast_title
            ensure_dir_exists(podcast_dir)

            episode_file = podcast_dir / (snipd_ep.episode_title + ".md")
            # create new file 
            if not episode_file.exists():
                episode_file.write_text(snipd_ep.full_page)
                logger.info(f"Episode created:: {episode_file.name}")

            # append to existing file
            else:
                # Use `open` as cannot append with pathlib
                with open(episode_file, "a") as file_handle:
                    episode_content = (
                        f"\n\n***(Appended {str(date.today())})***\n\n" +
                        snipd_ep.page_body
                    ) 
                    file_handle.write(episode_content)
                logger.info(f"Episode appended: {episode_file.name}")


if __name__ == "__main__":
    from readwise_local_plus.config import fetch_user_config

    user_config = fetch_user_config()

    write_batch_to_obsidian(user_config, 67)