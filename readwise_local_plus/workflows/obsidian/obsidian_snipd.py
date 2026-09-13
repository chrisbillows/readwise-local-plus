import logging
from pathlib import Path

from readwise_local_plus.config import UserConfig, fetch_user_config
from readwise_local_plus.db_export import DbHls

logger = logging.getLogger(__name__)


REQUIRED_CATEGORY_DIRS = ["podcasts"]
# key is rw name, value is desired name

PODCAST_TITLE_MAP = {
    "The Rest Is History": "Rest Is History",
    "The Rest Is Politics": "Rest Is Politics",
}


def ensure_dir_exists(dir_path: Path, parents: bool = False) -> None:
    if not dir_path.is_dir():
        dir_path.mkdir(parents=parents)  # Error if exists, or parents don't exist
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


def write_dbhls_to_obsidian(
    user_config: UserConfig,
    query_shortname: str,
    batch_id: int | str,
) -> None:
    """
    Entry point function to write a batch of highlights to Obsidian.

    Parameters
    ----------
    user_config: UserConfig
        A RWLP user config object.
    query_shortname: str
        A query shortname that appears in `db_export.DbHls.DB_QUERIES`
    batch_id: int | str
        A batch_id to "all" for all Hls meeting the query, regardless of
        batch.
    """
    ensure_readwise_dirs(user_config)

    dbhls = DbHls(query_shortname, batch_id)
    # TODO: Add output from analysis obj for monitoring?

    for snipd_ep in dbhls.hls_by_snipd_url:
        snipd_ep.populate()

        # `podcasts` aka BookFromDb.category is hardcoded for consistency
        podcast_dir = user_config.obsidian_rw_dir / "podcasts" / snipd_ep.podcast_title
        ensure_dir_exists(podcast_dir)

        episode_file = podcast_dir / (snipd_ep.episode_title + ".md")

        if not episode_file.exists():
            logger.info(
                "Episode created: %s | %s", snipd_ep.podcast_title, episode_file.name
            )
        else:
            logger.info(
                "Episode overwritten: %s | %s",
                snipd_ep.podcast_title,
                episode_file.name,
            )

        episode_file.write_text(snipd_ep.full_page)


if __name__ == "__main__":
    # Use for experimentation/development of the `db_export.py`.
    from readwise_local_plus.config import fetch_user_config
    from readwise_local_plus.configure_logging import setup_logging

    setup_logging()

    user_config = fetch_user_config()
    query_shortname = "snipd"

    # Useful batches
    # batch_id = "all" # ~890 snipd books
    # batch_id = 110 # 0 snipd books
    # batch_id = 111 # 376 snipd books
    batch_id = 112  # 1 snipd books
    # batch_id = 113 # 10 snipd books

    write_dbhls_to_obsidian(user_config, query_shortname, batch_id)
