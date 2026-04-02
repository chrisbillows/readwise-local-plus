import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

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

from readwise_local_plus.workflows.tree import Node

logger = logging.getLogger(__name__)

@dataclass
class DNHighlight:
    """Fields required to export a highlight to a Roam Daily Note."""
    user_book_id: int
    id: int
    text: str
    note: str | None
    location: int | None
    created_at: datetime | None
    updated_at: datetime | None
    url: str | None
    readwise_url: str | None
    book_title: str | None
    book_category: str | None
    book_author: str | None
    book_source_url: str | None

    def __repr__(self):
        text = self.text[:80]
        if len(text) == 80:
            text += "..."
        return f'DNHiglight(Text="{text}"'


class DNHighlightsPayload:
    """
    Build plain-Python daily note payloads from ORM highlights.
    """
    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        self._session: Session = get_session(fetch_user_config().db_path)
        self.raw_highlights = []
        self.dn_highlights = []
        self.grouped_highlights = defaultdict(lambda: defaultdict(list))

    def build(self):
        self._fetch_raw_highlights()
        self._convert_highlights()
        
        # for hl in self.dn_highlights:
        #     print(hl)
        
        self._group_highlights()
        self._session.close()
        return self.grouped_highlights

    def _fetch_raw_highlights(self):
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
        logger.info(f"{len(self.raw_highlights)} highlights in batch {self.batch_id}")

    def _convert_highlights(self):
        for highlight in self.raw_highlights:
            dn_highlight = DNHighlight(
                user_book_id=highlight.book.user_book_id,
                id=highlight.id,
                text=highlight.text,
                note=highlight.note,
                location=highlight.location,
                created_at=highlight.created_at,
                updated_at=highlight.updated_at,
                url=highlight.url,
                readwise_url=highlight.readwise_url,
                book_title=highlight.book.title,
                book_author=highlight.book.author,
                book_category=highlight.book.category,
                book_source_url=highlight.book.source_url,
            )
            self.dn_highlights.append(dn_highlight)      

    def _group_highlights(self):
        for dn_highlight in self.dn_highlights:
            daily_note_date = dn_highlight.created_at.date()
            book = dn_highlight.user_book_id
            self.grouped_highlights[daily_note_date][book].append(dn_highlight)


def ensure_payload_daily_notes_exist(dn_highlight_payload):
    """
    Ensure the daily note for the payload's target date exists in Roam, creating it if necessary.

    Daily notes are stored in the RoamKnownPage table.
    """
    roam_client = RoamClient()
    session = get_session(fetch_user_config().db_path) 
    
    for daily_note in dn_highlight_payload.keys():
        # WHAT ARE WE ITERATING OVER HERE?
        daily_note_uid = roam_client.date_to_roam_daily_note(daily_note)
        existing_page = session.get(RoamKnownPage, daily_note_uid)
        if (
            existing_page is None
            and session.get(RoamKnownPage, daily_note_uid) is None
        ):
            print("logic trigggered")
            daily_note_long_format = (
                roam_client._format_daily_note_title_long_format(daily_note)
            )
            try:
                roam_client.create_page(daily_note_long_format, exists_ok=True)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to ensure daily note %s exists: %s",
                    daily_note_uid,
                    exc,
                )
            session.add(
                RoamKnownPage(page_uid=daily_note_uid, last_verified_at=datetime.now())
            )
            session.commit()
        else:
            print("logic not triggered")
        session.close()


# class FormatedBookTrees:


def main(batch_id: int):
    dnhp = DNHighlightsPayload(batch_id)
    grouped_highlights = dnhp.build()
    # ensure_payload_daily_notes_exist(grouped_highlights)
    
    # for daily_note_date, book_dict in grouped_highlights.items():
                
    #     print(daily_note_date.isoformat())
        
    #     for book_id, highlights in book_dict.items():
    #         print(f"{book_id} - {len(highlights)} hls")
        
    # create trees
    daily_note_nodes = []
    for daily_note_date, book_dict in grouped_highlights.items():
        
        daily_note_date: date
        book_dict: dict[int, DNHighlight]
        
        daily_note_node = Node("daily_note", daily_note_date)
        
        for book_id, highlights in book_dict.items():
            book_node = Node("book_header", book_id)
            daily_note_node.add_child(book_node)

            book_summary_node = Node("book_summary", "#[[rw]] #[[]]")
            book_node.add_child(book_summary_node)

            for highlight in highlights:
                highlight: DNHighlight
                highlight_node = Node("highlight_text", highlight.text)
                book_summary_node.add_child(highlight_node)
                if highlight.note:
                    note_node = Node("highlight_note", highlight.note)
                    highlight_node.add_child(note_node)
        
        daily_note_nodes.append(daily_note_node)

    print(daily_note_nodes)

if __name__ == "__main__":
    batch_id = 60  
    main(batch_id)    
    






    # date_nodes = set()
    # book_nodes = set()

    # for dn_date in pl.daily_note_dates:
    #     layer_1 = Node("daily_note", dn_date)
    #     date_nodes.append(layer_1)

    # for book in pl.books:
    #     layer_2 = format_book_header(book)

    # for highlight in pl.highlights:
    #     print(type(highlight))

    # rba = RoamBatchAction()
    # rb = rba.create_batch_action_body()

    # book = Node("title", "THE TWITS")
    # summary = Node("summary", "#[[Roald Dahl]] #[rw]] #[[books]]")
    # q1 = Node("highlight", "Quote1")
    # q2 = Node("highlight", "Quote2")
    # book.add_child(summary)
    # summary.add_child(q1)
    # summary.add_child(q2)

    # breakpoint()
