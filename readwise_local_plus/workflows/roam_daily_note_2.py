import hashlib
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from tldextract import extract

from readwise_local_plus.config import fetch_user_config
from readwise_local_plus.db_operations import get_session
from readwise_local_plus.integrations.roam import RoamBatchAction, RoamClient
from readwise_local_plus.models import (
    Book,
    Highlight,
    RoamBookExport,
    RoamExportBatch,
    RoamHighlightExport,
    RoamHighlightSnapshot,
    RoamKnownPage,
    RoamPage,
    RoamPageSnapshot,
)

logger = logging.getLogger(__name__)

# Text for the highlights header block. Highlights are written, by book,
# underneath this header. Only one header will be added to each daily note. No
# no ordering under the header is enforced.
HIGHLIGHTS_HEADER = "[[Readwise highlights]]"

@dataclass
class BookPayload:
    """
    A formatted book header and it's highlights ready for export to a daily note.
     
    This is the key unit of export. Additional parent or child or sibling blocks should be
    easily added to this structure as needed. i.e. keep this in mind for upstream and downstream
    processing.
    """
    book_header: str
    highlights: list[str]

@dataclass
class HighlightData:
    # From book
    user_book_id: int
    book_title: str | None
    book_category: str | None
    book_author: str | None
    book_source_url: str | None
    # From highlight
    id: int
    text: str
    note: str | None
    location: int | None
    created_at: datetime | None
    updated_at: datetime | None
    url: str | None
    readwise_url: str | None
    is_deleted: bool


    def __repr__(self) -> str:
        return f"{self.text[:30]}" if self.text else "No text"


class HighlightConverter:
    """
    Convert ORM highlights into dataclasses containing required fields for export.

    Decouple highlights from ORM session to avoid accidental mutation and ease of use.
    """

    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        self._session: Session = get_session(fetch_user_config().db_path)
        self.raw_highlights: list[Highlight] = []
        self.highlights: list[HighlightData] = []
        self.grouped_highlights = {}

    def convert(self) -> list[HighlightData]:
        """Driver."""
        self._fetch_raw_highlights()
        self._convert_highlights()
        self._group_highlights()
        self._session.close()
        return self.grouped_highlights

    def _fetch_raw_highlights(self):
        """Fetch ORM highlights for a Readwise batch."""
        stmt = (
            select(Highlight)
            .join(Highlight.book)
            .where(
                Highlight.batch_id == self.batch_id,
                (Book.category == "articles") | (Book.category == "tweets"),
            )
            .options(
                selectinload(Highlight.book).load_only(
                    Book.user_book_id,
                    Book.title,
                    Book.category,
                    Book.author,
                    Book.source_url,
                )
            )
            .order_by(Highlight.book_id, Highlight.id)
        )

        self.raw_highlights = self._session.execute(stmt).scalars().all()
        logger.info(
            "Fetched %s highlights for batch %s",
            len(self.raw_highlights),
            self.batch_id,
        )

    def _convert_highlights(self) -> None:
        """
        Convert ORM highlights to dataclasses for use in export.
        """
        for highlight in self.raw_highlights:
            book = highlight.book
            if book is None:
                continue

            highlight_data = HighlightData(
                user_book_id=highlight.book.user_book_id,
                book_title=highlight.book.title,
                book_category=highlight.book.category,
                book_author=highlight.book.author,
                book_source_url=highlight.book.source_url,
                id=highlight.id,
                text=highlight.text,
                note=highlight.note,
                location=highlight.location,
                created_at=highlight.created_at,
                updated_at=highlight.updated_at,
                url=highlight.url,
                readwise_url=highlight.readwise_url,
                is_deleted=highlight.is_deleted,
            )
            self.highlights.append(highlight_data)

    def _group_highlights(self) -> None:
        """Group highlights by daily note date and book."""
        for highlight in self.highlights:
            date = highlight.created_at.date()
            if date not in self.grouped_highlights:
                self.grouped_highlights[date] = {}
            if highlight.user_book_id not in self.grouped_highlights[date]:
                self.grouped_highlights[date][highlight.user_book_id] = []
            self.grouped_highlights[date][highlight.user_book_id].append(highlight)


class HighlightFormatter:
    """
    Format Highlights for writing to Roam daily notes.
    """

    def __init__(
            self, highlights: list[HighlightData]
        ) -> None:
        """
        Object init.

        Parameters
        ----------
        highlights : list[HighlightData]
            Fetched highlights grouped by daily note date.

        Attributes
        ----------
        highlights_header : str

        """
        self.highlights = highlights

    def run(self) -> None:
        """
        Driver method.
        """
        formatted_highlights: dict[datetime, list[dict]] = {}

        for daily_note in self.highlights:
            for book_group in daily_note.books:
                book = book_group.book
                highlights = book_group.highlights
                if book.category == "tweets": 
                    self._format_tweets()
                elif book.category == "articles":
                    self.format_article()
                elif book.category == "books":
                    self.format_book()
                else:
                    logger.warning(f"Unknown book category {book.category} for book {book.title}")
        return formatted_highlights

    def _format_book():
        """
        Format a highlight that came from a book.

        The term "book" is overloaded in Readwise. It mostly refers to the parent
        of a highlight. Here it refers to an actual book.
        """
        pass

    def _format_tweets(self, book: Book, date: date) -> None:
        """
        Format a tweet or tweets; book and highlight.

        Tweets will be grouped by user (and by day). Multiple tweets are possible.
        """
        edited_title = book.title.replace("Tweets", "Tweet")
        book_header = f"{edited_title} #[[tweets]] #[[rw]]"

        for highlight in book.highlights:
            content = highlight.content
            if highlight.note:
                content += f"\n\nNote: {highlight.note}"
            formatted_highlight = ""
        self.formatted_highlights[date] = formatted_highlight
    
    def _format_tweet_thread():
        pass
    
    def _format_article():
        pass


class DailyNotePageSupplier:
    """
    Validate that a Roam daily note page.
     
    - ensure it exists
    - ensure it contains a highlight header
    """
    pass


class RoamDailyNoteWriter:
    """
    Write highlights to a validated to a Roam daily note page.
    """
    pass

class DBPopulaterRoamExport:
    """
    Update DB with details of Roam post Daily note write state.
    """
    pass



if __name__ == "__main__":
    batch_id = 66
    payload_builder = HighlightConverter(batch_id)
    payload = payload_builder.convert()
    breakpoint()


    # for book in highlights.values():
    #     print(type(book))
    #     print(book.values())


# x = {
#   "action": "batch-actions",
#   "actions": [
#     {
#       "action": "create-block",
#       "location": {
#         "order": "last",
#         "parent-uid": "ERwJmpO5Y"
#       },
#       "block": {
#         "string": "Tweet Thread From Tim Ferriss #[[tweets]] #[[rw]] [↗️](https://x.com/tferriss/status/2036266171121467752/?rw_tt_thread=True)",
#         "uid": -1,
#         "heading": 3
#       }
#     },
#     {
#       "action": "create-block",
#       "location": {
#         "order": "last",
#         "parent-uid": -1
#       },
#       "block": {
#         "string": "the point of investing is ultimately to improve your quality of life [↗️](https://read.readwise.io/read/01kmgh6bkd0gxkqwe8gtf0n830)",
#         "uid": -2
#       }
#     },
#     {
#       "action": "create-block",
#       "location": {
#         "order": "last",
#         "parent-uid": -1
#       },
#       "block": {
#         "string": "investments that consistently add stress over long periods of time probably don’t make sense [↗️](https://read.readwise.io/read/01kmgh6qgr71y1g3nfg39s214j)",
#         "uid": -3
#       }
#     },
#     {
#       "action": "create-block",
#       "location": {
#         "order": "last",
#         "parent-uid": -1
#       },
#       "block": {
#         "string": "Money is a means, not an end [↗️](https://read.readwise.io/read/01kmgh71et6kzk7s4dgcpj03b7)",
#         "uid": -4
#       }
#     },
#     {
#       "action": "create-block",
#       "location": {
#         "order": "last",
#         "parent-uid": -1
#       },
#       "block": {
#         "string": "in the end, most things matter very, very little [↗️](https://read.readwise.io/read/01kmgh78e2rfjprch54sj41h52)",
#         "uid": -5
#       }
#     },
#     {
#       "action": "create-block",
#       "location": {
#         "order": "last",
#         "parent-uid": -1
#       },
#       "block": {
#         "string": "Do what helps you sleep at night and wake up with a low heart rate [↗️](https://read.readwise.io/read/01kmgh7g9gqpkvvt3ywr1bat4a)",
#         "uid": -6
#       }
#     }
#   ]
# }
