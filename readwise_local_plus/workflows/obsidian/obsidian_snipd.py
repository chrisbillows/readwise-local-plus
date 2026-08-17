from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date
import logging
from typing import Any
import os

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
    cover_image_url: str
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
                # Highlight.batch_id == self.batch_id,
                Book.category.in_(["podcasts"]),
                Book.source.is_("snipd"),
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
                    Book.cover_image_url,
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
                    cover_image_url = h.book.cover_image_url,
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

def obsidian_safe_filenames_and_frontmatter(file_name: str) -> str:
    ILLEGAL_CHARS_TABLE = str.maketrans(dict.fromkeys('*"\\/<>:|?#^[]'))
    if len(file_name) > 100:
        file_name = file_name[:100] 
    return file_name.translate(ILLEGAL_CHARS_TABLE)


def revise_podcast_title(raw_title: str) -> str:
    safe_title = obsidian_safe_filenames_and_frontmatter(raw_title)
    if safe_title in PODCAST_TITLE_MAP:
        safe_title = PODCAST_TITLE_MAP[safe_title]
    return safe_title


def create_episode_frontmatter(
        podcast_episode: BookFromDb, podcast_name: str, episode_name: str) -> str:
    """
    Create podcast frontmatter.

    Parameters
    ----------
    podcast_episode: BookFromDb
        The podcast episode object from the database.
    podcast_name: str
        The Obsidian safe, user revised podcast name.
    episode_name: str
        The Obsidian safe episode name.

    Returns
    -------
    str
        The front matter block as a string with newlines.
    """

    front_matter_template = """---
title: {{title}}
source: {{source}}
readwise_url: {{rw_url}}
listened: {{listened_date}}
created: {{created_date}}
tags:
- podcast/{{podcast_title}}
- podcast-eps
---
"""

    template_replacements = {
        "{{title}}": episode_name,
        "{{source}}": podcast_episode.source_url,  # snipd url
        "{{rw_url}}": podcast_episode.readwise_url,
        "{{listened_date}}": str(podcast_episode.highlights[0].created_at.date()),
        "{{created_date}}": str(date.today()),
        "{{podcast_title}}": podcast_name.lower().replace(" ", "-"),
    }

    for placeholder, value in template_replacements.items():
        front_matter_template = front_matter_template.replace(placeholder, value)
    return front_matter_template


def split_on_punctuation(quote: str) -> list:
    """
    Split text on punctuation into a list of strings.

    Handles ellipsis, fullstops, question marks and exclaimation marks.

    Parameters
    ----------
    quote: str
        A paragraph of text.

    Returns
    -------
    list
        The original text as a list of strings.
    """
    # Do first, preserve ellipsis
    quote = quote.replace("...", "...\n")
    quote = quote.replace(". ", ".\n")
    quote = quote.replace("? ", "?\n")

    split_quote = quote.split("\n")

    return split_quote


def split_transcript(raw: str) -> list[tuple[str, str]]:
    """
    Split transcript section of a highlight by speaker.

    Quotes expected to be formatted as:

    ```
    <speaker>
    <quote>
    ```

    Parameters
    ----------
    raw : str
        The speakers section of a highlight. Assumes text was split on 'Transcript:' 
        therefore begins with a newline. Assumes quotes follow the format above.
            
    Returns
    -------
    list[tuple[str, str]]
        A list of tuples in the form [(<speaker>, <quote>), (<speaker>, <quote>)]
    """
    raw = raw[1:]
    raw = raw.replace("\n\n", "\n")
    raw = list(raw.split("\n"))

    transcript_by_speaker = []
    for even_idx in range(0, len(raw), 2):
        speaker = raw[even_idx]
        quote = raw[even_idx + 1]
        transcript_by_speaker.append((speaker, quote))
    return transcript_by_speaker


def format_transcript_hl_quotes(transcript: str) -> str:
    transcript_by_speaker = split_transcript(transcript)

    fmtd_complete_transcript = []
    for speaker, quote in transcript_by_speaker:
        split_quote = split_on_punctuation(quote)
        fmtd_split_quote = "".join([f"> - {str}\n" for str in split_quote])
        fmtd_transcript = f"> [!quote] **{speaker}**\n{fmtd_split_quote}"
        fmtd_complete_transcript.append(fmtd_transcript)

    return fmtd_complete_transcript


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


def highlight_format_type(hl: HighlightFromDb) -> str:
    """
    Return highlight format type.

    Types are `'transcript'`, `'episode-ai-notes'`. `'do-not-process'`
    indicates oddities we do not process.
    
    Parameters
    ----------
    hl : HighlightFromDB
        An extracted highlight
    
    Returns
    -------
    str
        A string indicating the highlight type.
    """
    if "Transcript:" in hl.text and "Episode AI notes" in hl.text:
        warning_msg = (
            "Highlight id: " +
            str(hl.id) +
            " in book id: " +
            str(hl.user_book_id) +
            " has 'Transcript:' and 'Episode AI notes:' strs. Did not process."
            )
        logger.warning(warning_msg)
        return "do-not-process"
    
    if "Transcript:" in hl.text:
        return "transcript"

    elif "Episode AI notes" in hl.text:
        return "episode-ai-notes"

    else:
        return "do-not-process"


def format_transcript_hl_title(hl_title: str) -> str:
    """
    Format a string as a transcript highlight title.
    """
    # Use first bullet as title
    hl_title = hl_title.replace("--", "")
    hl_title = hl_title.replace("**", "")

    if hl_title.startswith("-"):
        hl_title = hl_title[1:]

    return "## " + hl_title


def make_bullets(split_body: list[str], split_body_type: str) -> list[str]:
    """
    Add dashes to the start of a list of strings.
    """
    bullet_body = []
    for s in split_body:
        bullet_s = '- ' + s
        if split_body_type == "summary":
            bullet_s += "."
        bullet_body.append(bullet_s)
    return bullet_body


def process_transcript_hl_body(hl_body, hl_body_type) -> str:
    """
    Take a transcript highlight body and convert it to a writable string.

    Conversion depends on highlight body type.

    Parameters
    ----------
    hl_body : list[str]
        The summary section of a highlight, as a list of strings.
    hl_body_type: str
        The highlight body type

    Returns
    -------
    str
        The list of strings, formatted for writing, usually as a bullets seperated by
        newlines.
    """
    match hl_body_type:
        case "no-body":
            return ""
        case "bullets":
            return "\n".join(hl_body)
        case "summary":
            hl_body = [s for s in hl_body if s != "Summary:"]
            bullet_body = make_bullets(hl_body, hl_body_type)
            return "\n".join(bullet_body)
        case "single-block":
            split_body = hl_body[0].split(". ")
            bullet_body = make_bullets(hl_body, hl_body_type)
            return "\n".join(bullet_body)
        case "multi-line":
            bullet_body = make_bullets(hl_body, hl_body_type)
            return "\n".join(bullet_body)
        case _:
            print(hl_body)
            raise


def transcript_hl_body_type(hl_body: list[str]) -> str:
    """
    Return the 'type' of a transcript highlight body.
    """
    if len(hl_body) == 0:
        return "no-body"

    elif hl_body[0].startswith('-'):
        return "bullets"

    elif "Summary:" in hl_body:
        return "summary"

    elif len(hl_body) == 1:
        return "single-block"

    elif len(hl_body) > 1:
        return "multi-line"

    else:
        logger.warning("ODD BLOCK BRO!")


def split_transcript_hl_summary(summary: str) -> tuple[str, list[str]]:
    """
    Split a transcript highlight summary into a `title` and `body`.

    Returns
    -------
    tuple
        Where the first item is the highlight title as a string, and then 
        second item is the summary bullet points as a list of strings.
    """
    summary = summary.replace("\n\n", "\n")
    hl_summary_split = summary.split("\n")

    hl_title = hl_summary_split[0]
    hl_body = [s for s in hl_summary_split[1:] if s is not '']

    return hl_title, hl_body


def clean_transcript_hl_text(hl_text: str) -> str:
    """
    Initial clean of a transcript highlight's text.
    """
    # Remove the 'Key takeaways' str. Fmt otherwise is std bullets.
    text = hl_text.replace("Key takeaways:", "")
    # Make non-std bullets std.
    text = text.replace("•", "-")
    text = text.replace("*", "-")
    return text


def process_transcript_hl(hl: HighlightFromDb) -> str:
    """
    Process a transcript highlight (i.e. a highlight with the text 'Transcript':).

    Transcript highlights are split into two parts:
        - `summary` and `quotes`
    
    The `summary` is then split into:
        - `hl_header` and `hl_body`
         
    Returns
    -------
    str
        The recombined, formatted highlight as a writeable string.
    """
    cleaned_text = clean_transcript_hl_text(hl.text)
    summary, quotes = cleaned_text.split("Transcript:")

    hl_title, hl_body = split_transcript_hl_summary(summary)
    hl_body_type = transcript_hl_body_type(hl_body)

    fmtd_title = format_transcript_hl_title(hl_title)
    fmtd_body = process_transcript_hl_body(hl_body, hl_body_type)
    fmtd_quotes = format_transcript_hl_quotes(quotes)
    
    fmtd_highlight = fmtd_title + "\n\n" + fmtd_body + "\n\n" + "\n".join(fmtd_quotes) + "\n\n"

    return fmtd_highlight


def print_highlight_type_stats(list_of_hls_by_book: list[dict[int, HighlightFromDb]]) -> None:
    """
    Print summary of highlight types.

    Counts split of highlights as `transcript`, `episode ai notes` or `do not process`. And
    counts split of transcript highlights into `nobody`, `bullets`, `summary` etc.
    
    """
    count_of_transcript = 0
    count_of_episode_ai_notes = 0
    count_of_do_not_process = 0

    count_of_nobody = 0
    count_of_bullets = 0
    count_of_summary = 0
    count_of_single_block = 0
    count_of_multi_line = 0


    # Count highlight types
    for podcast in list_of_hls_by_book.values():
        for hl in podcast.highlights:
            hl_type = highlight_format_type(hl) 
            if hl_type == 'transcript':
                count_of_transcript += 1

                hl_body_type = ""

                match hl_body_type:
                        case "no-body":
                            count_of_nobody += 1
                        case "bullets":
                            count_of_bullets += 1
                        case "summary":
                            count_of_summary += 1
                        case "single-block":
                            count_of_single_block += 1
                        case "multi-line":
                            count_of_multi_line += 1

            elif 'episode-ai-notes': 
                count_of_episode_ai_notes += 1
            elif hl_type == 'do-not-process':
                count_of_do_not_process += 1            

    print("TYPES OF HIGHLIGHT:")
    print(f"  {count_of_transcript:7} - Contain str 'Transcript:'")
    print(f"  {count_of_episode_ai_notes:7} - Contain str 'Episode AI Notes:'")
    print(f"  {count_of_do_not_process:7} - Oddities we do not process")
    total_highlights = (
        count_of_transcript + count_of_episode_ai_notes + count_of_do_not_process
    )
    print(f"  {total_highlights:7} - TOTAL HIGHLIGHTS COUNTED\n\n")

    print("TYPES OF TRANSCRIPT_HIGHLIGHT_BODY")
    print(f"  {count_of_nobody:7} - Empty body")
    print(f"  {count_of_bullets:7} - Bullets")
    print(f"  {count_of_summary:7} - Summary")
    print(f"  {count_of_single_block:7} - Single block")
    print(f"  {count_of_multi_line:7} - Multi-line")
    total_ts_highlights = (
        count_of_nobody + count_of_bullets + count_of_summary + count_of_single_block +
        count_of_multi_line
    )
    print(f"  {total_ts_highlights:7} - TOTAL TRANSCRIPT HIGHLIGHTS COUNTED\n\n")


def write_batch_to_obsidian(user_config: UserConfig, batch_id: int):
    """Entry point function to write a batch of highlights to Obsidian."""
    ensure_readwise_dirs(user_config)
    batch_highlights = get_batch_highlights(batch_id)

    print_highlight_type_stats(batch_highlights)

    # each `BookFromDb` obj is a podcast_episode
    for user_book_id, podcast_episode in batch_highlights.items():

        # 0 ---- CREATE GENERAL VARS

        raw_podcast_title = podcast_episode.author
        revised_podcast_title = revise_podcast_title(raw_podcast_title)
        safe_podcast_title = obsidian_safe_filenames_and_frontmatter(podcast_episode.title)

        # create podcast dir after no errors in content
        # 1 ---- CREATE EPISODE FILE CONTENT

        episode_front_matter = create_episode_frontmatter(
            podcast_episode, revised_podcast_title, safe_podcast_title
        )
        
        episode_content = []

        for hl in podcast_episode.highlights:
            hl_type = highlight_format_type(hl)
            match hl_type:
                case "transcript":
                    fmtd_hl = process_transcript_hl(hl)
                case "episode-ai-notes":
                    fmtd_hl = ""
                case "do-not-process":
                    pass
                case _:
                    msg = f"WARNING: Highlight ID: {hl.id} is of unknown type. Not processed."
                    logger.warning(msg)
            episode_content.append(fmtd_hl)

        episode_content = "".join(episode_content)

        episode_content_and_fm = episode_front_matter + "\n" + episode_content

        # 3 ---- ADD SNIPD METADATA (will come from db)

        # a) pull metadata from db
        # b) format db metadata
        # c) add metadata to batch episode content

        # 4 ---- ENSURE POD DIR EXISTS

        # `podcasts` aka book.category is hardcoded for consistency
        podcast_dir = user_config.obsidian_rw_dir / "podcasts" / revised_podcast_title
        ensure_dir_exists(podcast_dir)

        # 5 ---- WRITE / APPEND EPISODE CONTENT
        episode_file = podcast_dir / (safe_podcast_title + ".md")

        if not episode_file.exists():
            # file create logic
            episode_file.write_text(episode_content_and_fm)
            logger.info(f"Episode created:: {episode_file.name}")
        else:
            # file append logic
            # Use `open` as cannot append with pathlib
            with open(episode_file, "a") as file_handle:
                episode_content = f"\n\n***(Appended {str(date.today())})***\n\n" + episode_content
                file_handle.write(episode_content)
            logger.info(f"Episode appended: {episode_file.name}")
