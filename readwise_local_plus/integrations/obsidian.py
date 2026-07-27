from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from pathlib import Path

from readwise_local_plus.config import UserConfig, fetch_user_config
from readwise_local_plus.db_operations import get_session

from readwise_local_plus.models import (
    Book,
    Highlight,
)


logger = logging.getLogger(__name__)


REQUIRED_CATEGORY_DIRS = ["podcasts"]
# key is rw name, value is desired name

PODCAST_TITLE_MAP = {
    "The Rest Is History": "Rest Is History",
    "The Rest Is Politics": "Rest Is Politics",
}


# Duplicate from chatgpt_daily_prototype - likely pull out into new module and combine
@dataclass
class HighlightFromDb:
    user_book_id: int
    id: int
    text: str
    note: str | None
    location: int | None
    created_at: datetime | None
    updated_at: datetime | None
    url: str | None
    readwise_url: str | None

    def __repr__(self) -> str:
        return f"HL()"


# Duplicate from chatgpt_daily_prototype - likely pull out into new module and combine
@dataclass
class BookFromDb:
    user_book_id: int
    title: str
    author: str
    readable_title: str
    source: str
    unique_url: str
    category: str
    readwise_url: str
    source_url: str
    highlights: list[HighlightFromDb] = field(default_factory=list)

    def __repr__(self) -> str:
        total_highlights = len(self.highlights)
        return f"Book(HLs: {total_highlights} | {self.title})"


# Duplicate from chatgpt_daily_prototype - likely pull out into new module and combine
class DbData:
    """
    Build daily note payload:
    dict[date] -> list[DNBook]
    """

    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        self._session: Session = get_session(fetch_user_config().db_path)
        self.grouped = {}

    def build(self) -> dict[int, BookFromDb]:
        logger.info("Create payload for batch: %s", self.batch_id)

        rows = self._fetch()

        for row in rows:
            self._process_row(row)

        self._session.close()

        return self.grouped

    def _fetch(self) -> list[Highlight]:
        stmt = (
            select(Highlight)
            .join(Highlight.book)
            .where(
                Highlight.batch_id == self.batch_id,
                Book.category.in_(["podcasts"]),
                Highlight.is_discard.is_(False),
            )
            .options(
                selectinload(Highlight.book).load_only(
                    Book.user_book_id,
                    Book.title,
                    Book.category,
                    Book.author,
                    Book.source,
                    Book.source_url,
                    Book.unique_url,
                    Book.readwise_url,
                    Book.readable_title,
                )
            )
            .order_by(Highlight.created_at, Highlight.book_id, Highlight.id)
        )

        rows = self._session.execute(stmt).scalars().all()
        logger.info("%s highlights fetched", len(rows))
        return rows
    
    def _clean_author(self, author: str, mappings: dict = PODCAST_TITLE_MAP) -> str:
        """
        Convert 'author' to preferred format.

        For podcasts, 'author' is the podcast name. In Obsidian this will be the parent
        directory. Overwrite readwise default with user preferred value defined in
        PODCAST_DIR_MAP.
        """
        if author in mappings.keys():
            return mappings[author]
        else:
            return author

    def _process_row(self, h: Highlight) -> None:
        book_id = h.book.user_book_id

        if not self.grouped.get(book_id):
            clean_author = self._clean_author(h.book.author) 
            self.grouped[book_id] = BookFromDb(
                    user_book_id=book_id,
                    title=h.book.title,
                    author=clean_author,
                    readable_title=h.book.readable_title,
                    source=h.book.source,
                    category=h.book.category,
                    unique_url=h.book.unique_url,
                    readwise_url=h.book.readwise_url,
                    source_url=h.book.source_url,
                )

        self.grouped[book_id].highlights.append(
            HighlightFromDb(
                user_book_id=book_id,
                id=h.id,
                text=h.text,
                note=h.note,
                location=h.location,
                created_at=h.created_at,
                updated_at=h.updated_at,
                url=h.url,
                readwise_url=h.readwise_url,
            )
        )

# --- WIP stuff figuring out processing steps ---
# ----  Makes most sense as a method on BookFromDb or HighlightFromDb? ---



def obsidian_safe_filenames(file_name: str) -> str:
    ILLEGAL_CHARS_TABLE = str.maketrans(dict.fromkeys('*"\//<>:|?#^[]'))
    return file_name.translate(ILLEGAL_CHARS_TABLE)


def revise_podcast_title(raw_title: str) -> str:
    safe_title = obsidian_safe_filenames(raw_title)
    if safe_title in PODCAST_TITLE_MAP:
        safe_title = PODCAST_TITLE_MAP[safe_title]
    return safe_title


def create_hl_frontmatter():
    pass


def split_quotes(raw_quote: str) -> str:
    split_quote = raw_quote.split(". ")
    return split_quote


def split_transcript(raw: str) -> list[tuple[str, str]]:
    raw = raw[12:]
    raw = raw.replace("\n\n", "\n")
    raw = list(raw.split("\n"))

    transcript_by_speaker = []
    for even_idx in range(0, len(raw), 2):
        speaker = raw[even_idx]
        quote = raw[even_idx + 1]
        transcript_by_speaker.append((speaker, quote))
    return transcript_by_speaker


def format_hl_title(title_text: str) -> str:
    title_text = title_text.replace("**", "")
    return "# " + title_text


def format_highlight(hl_text: HighlightFromDb) -> str:
    title, summary, transcript = hl_text.split("\n\n", 2)

    fmtd_title = format_hl_title(title)

    transcript_by_speaker = split_transcript(transcript)

    for speaker, quote in transcript_by_speaker:
        split_quote = split_quotes(quote)
        fmtd_split_quote = "".join([f"> - {str}\n" for str in split_quote])

        fmtd_transcript = f"> [!quote] {speaker}\n{fmtd_split_quote}"

    fmtd_highlight = fmtd_title + "\n\n" + summary + "\n\n" + fmtd_transcript + "\n\n"
     
    return fmtd_highlight


def get_batch_highlights(batch_id: int) -> dict[int, BookFromDb]:
    """Fetch highlights for a given batch from the RW db."""
    db_data = DbData(batch_id)
    grouped_highlights = db_data.build()
    return grouped_highlights


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
    batch_highlights = get_batch_highlights(batch_id)

    # each `Book` obj is a podcast_episode
    for user_book_id, podcast_episode in batch_highlights.items():

        # create podcast dir after no errors in content
        # 1 ---- CREATE EPISODE FILE CONTENT
        
        batch_episode_content = []
        for hl in podcast_episode.highlights:
            fmtd_hl = format_highlight(hl.text)
            batch_episode_content.append(fmtd_hl)

        batch_episode_content = "".join(batch_episode_content)

        # 2 ---- ENSURE POD DIR EXISTS

        raw_podcast_title = podcast_episode.author
        revised_podcast_title = revise_podcast_title(raw_podcast_title)

        # `podcasts` aka book.category is hardcoded for consistency
        podcast_dir = user_config.obsidian_rw_dir / "podcasts" / revised_podcast_title
        ensure_dir_exists(podcast_dir)

        # 3 ---- WRITE / APPEND EPISODE CONTENT

        episode_name = obsidian_safe_filenames(podcast_episode.title) + ".md"
        episode_file = podcast_dir / episode_name

        if not episode_name.exists():
            # file create logic
            episode_file.write_text(batch_episode_content)
            logger.info(f"Episode created:: {episode_file.name}")
        else:
            # file append logic
            ### CREATE APPEND LOGIC WITH OPEN - CANT WITH PATHLIB
            logger.info(f"Episode appended: {episode_file.name}")
