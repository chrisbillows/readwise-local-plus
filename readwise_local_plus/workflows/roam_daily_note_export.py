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

from readwise_local_plus.workflows.graph import Node

logger = logging.getLogger(__name__)

@dataclass
class HighlightExhaustive:
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


@dataclass(frozen=True)
class BookData:
    user_book_id: int
    title: str | None
    category: str | None
    author: str | None
    source_url: str | None


@dataclass(frozen=True)
class HighlightData:
    user_book_id: int
    id: int
    text: str
    note: str | None
    location: int | None
    created_at: datetime | None
    updated_at: datetime | None
    url: str | None
    readwise_url: str | None

    def __repr__(self):
        return()
        

@dataclass
class Payload:
    daily_note_dates: date
    books: list[BookData]
    highlights: list[HighlightData]

    def __repr__(self) -> str:
        return (
            f"daily-notes:{",".join([d.isoformat() for d in self.daily_note_dates])} "
            f"books:{len(self.books)} hls:{len(self.highlights)}"
        )

class PayloadBuilder:
    """
    Build plain-Python daily note payloads from ORM highlights.
    """

    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        self._session: Session = get_session(fetch_user_config().db_path)

    def build(self) -> list[Payload]:
        raw_highlights = self._fetch_raw_highlights()
        payload = self._process_highlights_exhaustive(raw_highlights)
        self._session.close()
        return payload

    def _fetch_raw_highlights(self) -> list[Highlight]:
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

        raw_highlights = self._session.execute(stmt).scalars().all()
        logger.info(
            "Fetched %s highlights for batch %s",
            len(raw_highlights),
            self.batch_id,
        )
        return raw_highlights


    def _process_highlights_exhaustive(self, raw_highlights: list[Highlight]):
        hles = []
        for highlight in raw_highlights:
            book = highlight.book
            if book is None:
                continue
            hle = HighlightExhaustive(
                user_book_id=book.user_book_id,
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
            hles.append(hle)
        return hles

    def _process_highlights(self, raw_highlights: list[Highlight]):
        book_ids_seen = set()
        
        dates = set()
        books = []
        highlights = []

        for highlight in raw_highlights:
            book = highlight.book
            if book is None:
                continue

            if book.user_book_id not in book_ids_seen:
                book_data = BookData(
                    user_book_id=book.user_book_id,
                    title=book.title,
                    category=book.category,
                    author=book.author,
                    source_url=book.source_url,
                )
                books.append(book_data)
                book_ids_seen.add(book.user_book_id)

            highlight_data = HighlightData(
                user_book_id=book.user_book_id,
                id=highlight.id,
                text=highlight.text,
                note=highlight.note,
                location=highlight.location,
                created_at=highlight.created_at,
                updated_at=highlight.updated_at,
                url=highlight.url,
                readwise_url=highlight.readwise_url,
            )
            highlights.append(highlight_data)

            if not highlight.created_at:
                logger.warning(
                    "Highlight %s has no created_at timestamp; using today's date for grouping",
                    highlight.id,
                )
                continue
            dates.add(highlight.created_at.date())

        return Payload(
            daily_note_dates=list(dates), books=list(books), highlights=highlights
        )

    # def _group_highlights_by_book(
    #     self, highlights: list[tuple[BookData, HighlightData]]
    # ) -> dict[BookData, list[HighlightData]]:
    #     highlights_by_book: dict[BookData, list[HighlightData]] = defaultdict(list)

    #     for book, highlight in highlights:
    #         highlights_by_book[book].append(highlight)

    #     for book_highlights in highlights_by_book.values():
    #         if book_highlights[0].location is not None:
    #             book_highlights.sort(key=lambda h: h.location or 0)
    #         else:
    #             book_highlights.sort(key=lambda h: h.created_at or datetime.min)

    #     return dict(highlights_by_book)

    # def _group_books_by_date(
    #     self, highlights_by_book: dict[BookData, list[HighlightData]]
    # ) -> list[DailyNotePayload]:
    #     grouped_by_date: dict[date, list[BookHighlights]] = defaultdict(list)

    #     for book, highlights in highlights_by_book.items():
    #         target_date = (
    #             highlights[-1].created_at.date()
    #             if highlights[-1].created_at
    #             else date.today()
    #         )
    #         grouped_by_date[target_date].append(
    #             BookHighlights(book=book, highlights=highlights)
    #         )

    #     return [
    #         DailyNotePayload(target_date=target_date, books=books)
    #         for target_date, books in sorted(grouped_by_date.items())
    #     ]
    
class DNPageManager:

    def __init__(self, payload: Payload) -> None:
        self.payload = payload
        self.roam_client = RoamClient()
        self._session: Session = get_session(fetch_user_config().db_path)

    def ensure_daily_note_exists(self) -> None:
        """
        Ensure the daily note for the payload's target date exists in Roam, creating it if necessary.

        Daily notes are stored in the RoamKnownPage table.
        """
        # daily_note = self.payload.target_date
        daily_note = date(2025, 3, 28)   
        daily_note_uid = self.roam_client.date_to_roam_daily_note(daily_note)
        existing_page = self._session.get(RoamKnownPage, daily_note_uid)
        if (
            existing_page is None
            and self._session.get(RoamKnownPage, daily_note_uid) is None
        ):
            print("logic trigggered")
            daily_note_long_format = (
                self.roam_client._format_daily_note_title_long_format(daily_note)
            )
            try:
                self.roam_client.create_page(daily_note_long_format, exists_ok=True)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to ensure daily note %s exists: %s",
                    daily_note_uid,
                    exc,
                )
            self._session.add(
                RoamKnownPage(page_uid=daily_note_uid, last_verified_at=datetime.now())
            )
            self._session.commit()
        else:
            print("logic not triggered")
        self._session.close()

   


# class ExportPayloadsCreator:
    


#     def __init__(self, payload: Payload) -> None:
#         self.payload = payload

#     def created_book_payloads_by_date(self) -> dict[date, list[BookData]]:





#         payloads_by_date: dict[date, list[BookData]] = defaultdict(list)
#         for book in self.payload.books:
#             book_highlights = [
#                 h for h in self.payload.highlights if h.user_book_id == book.user_book_id
#             ]
#             if not book_highlights:
#                 continue
#             target_date = (
#                 book_highlights[-1].created_at.date()
#                 if book_highlights[-1].created_at
#                 else date.today()
#             )
#             payloads_by_date[target_date].append(book)
#         return dict(payloads_by_date)

class ExportSingleDailyNote:
    """
    Daily notes are already proven to exist seperately

    Batch by daily note.
    """


    def __init__(self, payload: Payload, daily_note_date: date) -> None:
        self.daily_note_date = daily_note_date
        self.roam_client = RoamClient()
        self.roam_batch_action = RoamBatchAction()
        self.header_uid = self.retrieve_or_create_rw_header()
 
    def retrieve_or_create_rw_header(self):
        pass

    # def add_book_header(self):
    #     book_block_uid_candidate = self.roam_batch_action.append_a_child_block_action(
    #             self.header_uid,
    #             book_header,
    #             heading=3,
    #         )

    # def add_highlights(self):
    #     pass

    def add_book_graph_to_batch_action():
        pass



def write_confirmation_to_db():
    pass


def format_book_header():
    pass

if __name__ == "__main__":
    batch_id = 65
    pb = PayloadBuilder(batch_id)
    pl: Payload = pb.build()

    breakpoint()

    # date_nodes = set()
    # book_nodes = set()

    # for dn_date in pl.daily_note_dates:
    #     layer_1 = Node("daily_note", dn_date)
    #     date_nodes.append(layer_1)

    # for book in pl.books:
    #     layer_2 = format_book_header(book)

    # for highlight in pl.highlights:
    #     print(type(highlight))

    rba = RoamBatchAction()
    rb = rba.create_batch_action_body()

    book = Node("title", "THE TWITS")
    summary = Node("summary", "#[[Roald Dahl]] #[rw]] #[[books]]")
    q1 = Node("highlight", "Quote1")
    q2 = Node("highlight", "Quote2")
    book.add_child(summary)
    summary.add_child(q1)
    summary.add_child(q2)

    breakpoint()
