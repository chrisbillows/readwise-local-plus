"""
Fetch highlights based on a ReadwiseBatch id and write them to a Roam daily note.

The daily note will be the `created_at` date of the last highlight in the container book
object.

Currently only tweets and articles (hardcoded) are actioned.

"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

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
    RoamPage,
    RoamPageSnapshot,
)


@dataclass
class StagedBookExport:
    """
    Book export that will be persisted after the batch action runs.

    Attributes
    ----------
    user_book_id : int
        Identifier of the Readwise book whose block is being exported.
    page_uid : str
        UID of the daily note page that will host the exported block.
    temp_uid : str | int
        Temporary UID returned by the batch action (or an existing UID).
    """

    user_book_id: int
    page_uid: str
    temp_uid: str | int


@dataclass
class HighlightBlockSpec:
    """Describe a Roam block to be created for a highlight."""

    text: str
    heading: int | None = None
    open: bool | None = None
    is_primary: bool = False
    children: list["HighlightBlockSpec"] = field(default_factory=list)


@dataclass
class HighlightBlockPlan:
    """Plan describing how to render a highlight into Roam blocks."""

    root: HighlightBlockSpec


@dataclass
class StagedHighlightExport:
    """Highlight export that will be persisted after the batch action runs."""

    highlight_id: int
    page_uid: str
    primary_temp_uid: str | int
    export_date: datetime


@dataclass
class StagedHighlightSnapshot:
    """Highlight snapshot data staged until temp UIDs are resolved."""

    highlight_id: int
    block_tree: dict[str, Any]
    version: int


@dataclass
class StagedExports:
    """Aggregate of staged export artifacts for a daily note."""

    books: list[StagedBookExport]
    highlights: list[StagedHighlightExport]
    snapshots: list[StagedHighlightSnapshot]


@dataclass
class HighlightBlockRenderResult:
    """Result of rendering a highlight block plan into batch actions."""

    primary_temp_uid: str | int
    block_tree: dict[str, Any]


class RoamDailyNoteHighlightWriter:
    """
    Write highlights to Roam daily notes.
    """

    def __init__(self, batch_id: int) -> None:
        """
        Object init.

        Attributes
        ----------
        roam_client : RoamClient
            Client for interacting with the Roam API.
        highlights_header : str
            Text for the highlights header block. Highlights are written, by book,
            underneath this header. Only one header will be added by daily note. No
            distinction is made by batch, and no ordering under the header is enforced.
        highlights : dict[date, dict[Book, list[Highlight]]]
            Fetched highlights grouped by daily note date → book → highlights.
        _session : Session
            SQLAlchemy session for database operations.
        _batch : int
            Identifier of the ReadwiseBatch whose highlights should be processed.
        """
        self.roam_client = RoamClient()
        self.highlights_header = "[[Readwise highlights]]"
        self.highlights: dict[date, dict[Book, list[Highlight]]] = defaultdict(dict)
        self._session: Session = get_session(fetch_user_config().db_path)
        self._batch = batch_id

    def write_batch_to_daily_notes(self) -> None:
        """
        Driver method.
        """
        self.fetch_highlights()
        self._write_highlights()
        self._session.close()

    def fetch_highlights(self) -> None:
        """
        Fetch highlights for a batch, filtered for tweets & articles, grouped by
        daily note date → book_id → highlights.
        """
        stmt = (
            select(Highlight)
            .join(Highlight.book)
            .where(
                Highlight.batch_id == self._batch,
                (Book.category == "articles") | (Book.category == "tweets"),
            )
            .options(
                selectinload(Highlight.book).load_only(
                    Book.user_book_id, Book.title, Book.category
                )
            )
            .order_by(Highlight.book_id, Highlight.id)
        )

        highlights = self._session.execute(stmt).scalars().all()

        highlights_by_book: dict[Book, list[Highlight]] = defaultdict(list)
        for hl in highlights:
            highlights_by_book[hl.book].append(hl)

        for book, hls in highlights_by_book.items():
            # Sort by location or created at (e.g. for tweets).
            if hls[0].location is not None:
                hls.sort(key=lambda h: h.location or 0)
            else:
                hls.sort(key=lambda h: h.created_at or datetime.min)

            target_date = (
                hls[-1].created_at.date() if hls[-1].created_at else date.today()
            )
            self.highlights[target_date][book] = hls

    def create_formatted_book_header_by_category(self, book: Book) -> str:
        """
        Create a header block for a book highlight.

        Parameters
        ----------
        book : Book
            The book for which to create the header.

        Returns
        -------
        str
            Formatted header string for the book.
        """
        if not book.title:
            return "[ERROR]: Missing title"

        # Tweets and tweet threads.
        if book.category == "tweets":
            if not book.title.lower().startswith("tweets from"):
                author = book.author.split(" ")[0][1:] if book.author else "unknown"
                title = f"Tweet Thread From {author}"
            else:
                title = book.title
            return f"{title} #tweets #rw"

        if book.category == "articles":
            return book.title

        # Fallback for other categories (if any).
        return book.title

    def create_formatted_highlight_by_category(
        self, highlight: Highlight
    ) -> HighlightBlockPlan:
        """Return a block plan representing the highlight.

        Parameters
        ----------
        highlight : Highlight
            The highlight to format.

        Returns
        -------
        HighlightBlockPlan
            Block plan describing how to render the highlight.
        """
        text = highlight.text or "[ERROR]: Missing highlight text"

        book = getattr(highlight, "book", None)

        # Tweets: include the source URL (if available) as the parent block, with the
        # highlight text nested underneath. This keeps the primary export tied to the
        # text block while preserving the contextual link.
        if book and getattr(book, "category", None) == "tweets":
            url = getattr(highlight, "source_url", None)

            text_block = HighlightBlockSpec(text=text, is_primary=True)

            if url:
                root = HighlightBlockSpec(text=url, children=[text_block])
                return HighlightBlockPlan(root=root)

            return HighlightBlockPlan(root=text_block)

        # Default behaviour: single block containing the highlight text.
        return HighlightBlockPlan(root=HighlightBlockSpec(text=text, is_primary=True))

    @staticmethod
    def stable_hash(obj: dict[str, Any]) -> str:
        """
        Return a stable SHA256 hash for a JSON-serializable object.

        Parameters
        ----------
        obj : dict[str, Any]
            JSON-serializable object to hash.

        Returns
        -------
        str
            Hexadecimal SHA256 hash of the object.
        """
        # sort_keys=True ensures deterministic ordering
        return hashlib.sha256(
            json.dumps(obj, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _write_highlights(self) -> None:
        """
        Write fetched highlights to Roam daily notes.
        """
        if not self.highlights:
            return

        export_batch = RoamExportBatch(database_write_time=datetime.now())
        self._session.add(export_batch)

        for daily_note, books_and_highlights in self.highlights.items():
            self._process_daily_note(daily_note, books_and_highlights, export_batch)

        self._session.commit()

    def _process_daily_note(
        self,
        daily_note: date,
        books_and_highlights: dict[Book, list[Highlight]],
        export_batch: RoamExportBatch,
    ) -> None:
        """Process highlights for a single daily note page.

        Parameters
        ----------
        daily_note : date
            The date whose Roam daily note should be updated.
        books_and_highlights : dict[Book, list[Highlight]]
            Highlights grouped by their parent book for the target date.
        export_batch : RoamExportBatch
            Export batch that should be associated with all generated records.

        """
        daily_note_uid = self.roam_client.date_to_roam_daily_note(daily_note)

        existing_page = self._session.get(RoamPage, daily_note_uid)
        roam_batch_action = RoamBatchAction()

        if existing_page:
            header_uid_candidate: str | int = existing_page.highlights_header_uid
        else:
            header_uid_candidate = roam_batch_action.append_a_child_block_action(
                daily_note_uid,
                self.highlights_header,
                heading=1,
                open=True,
            )

        staged_exports = self._process_books_and_highlights(
            daily_note_uid,
            header_uid_candidate,
            books_and_highlights,
            roam_batch_action,
        )

        tempid_map = self._execute_batch_action(roam_batch_action)
        header_uid = self._resolve_uid(tempid_map, header_uid_candidate)

        page = self._upsert_page(
            existing_page,
            daily_note_uid,
            header_uid,
            export_batch,
        )

        self._add_staged_books_to_session(
            staged_exports.books, tempid_map, export_batch
        )
        self._add_staged_highlights_to_session(
            staged_exports.highlights, tempid_map, export_batch
        )
        self._add_staged_highlight_snapshots_to_session(
            staged_exports.snapshots, tempid_map, export_batch
        )

        self._create_page_snapshot(daily_note_uid, header_uid, page, export_batch)

    def _process_books_and_highlights(
        self,
        daily_note_uid: str,
        header_uid_candidate: str | int,
        books_and_highlights: dict[Book, list[Highlight]],
        roam_batch_action: RoamBatchAction,
    ) -> StagedExports:
        """Gather pending export artifacts for the supplied highlights.

        Parameters
        ----------
        daily_note_uid : str
            UID of the daily note that will be updated.
        header_uid_candidate : str or int
            UID (temporary or existing) for the highlights header block.
        books_and_highlights : dict[Book, list[Highlight]]
            Highlights grouped by book.
        roam_batch_action : RoamBatchAction
            Batch action instance to which new blocks should be appended.

        Returns
        -------
        PendingExports
            Collections describing the book exports, highlight exports, and
            snapshots that will need persistence once the batch action executes.
        """
        pending = StagedExports(books=[], highlights=[], snapshots=[])

        for book, highlights in books_and_highlights.items():
            self._process_book(
                daily_note_uid,
                header_uid_candidate,
                book,
                highlights,
                roam_batch_action,
                pending,
            )

        return pending

    def _process_book(
        self,
        daily_note_uid: str,
        header_uid_candidate: str | int,
        book: Book,
        highlights: list[Highlight],
        roam_batch_action: RoamBatchAction,
        pending: StagedExports,
    ) -> None:
        """Append book-level actions and queue persistence work.

        Parameters
        ----------
        daily_note_uid : str
            UID of the daily note page that owns the book content.
        header_uid_candidate : str or int
            UID (temporary or existing) for the header block under which books sit.
        book : Book
            Book that owns the supplied highlights.
        highlights : list[Highlight]
            Highlights belonging to the book.
        roam_batch_action : RoamBatchAction
            Batch action that collects the write operations.
        pending : PendingExports
            Collections to populate with pending database rows.

        """
        existing_book_export = self._get_existing_book_export(
            daily_note_uid, book.user_book_id
        )

        if existing_book_export:
            book_block_uid_candidate: str | int = existing_book_export.parent_block_uid
        else:
            book_header = self.create_formatted_book_header_by_category(book)
            book_block_uid_candidate = roam_batch_action.append_a_child_block_action(
                header_uid_candidate,
                book_header,
                heading=3,
            )
            pending.books.append(
                StagedBookExport(
                    user_book_id=book.user_book_id,
                    page_uid=daily_note_uid,
                    temp_uid=book_block_uid_candidate,
                )
            )

        for highlight in highlights:
            self._process_highlight(
                daily_note_uid,
                book_block_uid_candidate,
                highlight,
                roam_batch_action,
                pending,
            )

    def _process_highlight(
        self,
        daily_note_uid: str,
        book_block_uid_candidate: str | int,
        highlight: Highlight,
        roam_batch_action: RoamBatchAction,
        pending: StagedExports,
    ) -> None:
        """
        Queue write actions and persistence for an individual highlight.

        Parameters
        ----------
        daily_note_uid : str
            UID of the daily note page where the highlight will be written.
        book_block_uid_candidate : str or int
            UID (temporary or existing) of the parent book block.
        highlight : Highlight
            Highlight model that should be exported.
        roam_batch_action : RoamBatchAction
            Batch action that collects low-level write instructions.
        pending : PendingExports
            Collections to populate with pending database rows.

        """
        existing_export = self._get_existing_highlight_export(
            daily_note_uid, highlight.id
        )
        if existing_export:
            return

        # We can do type filtering here can't we? So we add custom logic for a highlight
        # when we want multiple "lines", e.g. the tweet link on a line, and the tweet
        # text nested beneath it.
        # ADD A `highlight_child` bool to this method.

        # if highlighted_child:
        #     pass

        # or maybe it's
        # formatted_highlight, highlight_child = self.create_formatted_highlight_by_category(highlight)
        # That could be a bool and later we do if highlight_child, then we call the logic - it might be better
        # to have pass the text into this method, and make this a generalised method that just appends a block
        # to a book.  Then the logic would just be at the process_book level?

        plan = self.create_formatted_highlight_by_category(highlight)
        render_result = self._render_highlight_block_tree(
            book_block_uid_candidate,
            plan.root,
            roam_batch_action,
        )

        pending.highlights.append(
            StagedHighlightExport(
                highlight_id=highlight.id,
                page_uid=daily_note_uid,
                primary_temp_uid=render_result.primary_temp_uid,
                export_date=datetime.now(),
            )
        )

        last_snapshot = self._get_last_highlight_snapshot(highlight.id)
        next_version = (last_snapshot.version + 1) if last_snapshot else 1

        pending.snapshots.append(
            StagedHighlightSnapshot(
                highlight_id=highlight.id,
                block_tree=render_result.block_tree,
                version=next_version,
            )
        )

    def _render_highlight_block_tree(
        self,
        parent_uid: str | int,
        block_spec: HighlightBlockSpec,
        roam_batch_action: RoamBatchAction,
    ) -> HighlightBlockRenderResult:
        temp_uid = roam_batch_action.append_a_child_block_action(
            parent_uid,
            block_spec.text,
            heading=block_spec.heading,
            open=block_spec.open,
        )

        children: list[dict[str, Any]] = []
        block_tree: dict[str, Any] = {
            "uid": temp_uid,
            "text": block_spec.text,
            "order": None,
            "children": children,
        }

        primary_temp_uid: str | int | None = temp_uid if block_spec.is_primary else None

        for child_spec in block_spec.children:
            child_result = self._render_highlight_block_tree(
                temp_uid, child_spec, roam_batch_action
            )
            children.append(child_result.block_tree)
            if primary_temp_uid is None:
                primary_temp_uid = child_result.primary_temp_uid

        if primary_temp_uid is None:
            primary_temp_uid = temp_uid

        return HighlightBlockRenderResult(
            primary_temp_uid=primary_temp_uid,
            block_tree=block_tree,
        )

    def _execute_batch_action(
        self, roam_batch_action: RoamBatchAction
    ) -> dict[str, str]:
        """Execute a batch action if it contains pending operations.

        Parameters
        ----------
        roam_batch_action : RoamBatchAction
            Batch action encapsulating the Roam write payload.

        Returns
        -------
        dict[str, str]
            Mapping of temporary UIDs to real Roam UIDs returned by the API. Empty
            if no actions were executed.
        """
        actions = roam_batch_action.batch_action_body.get("actions", [])
        if not actions:
            return {}
        return roam_batch_action.execute_batch_action() or {}

    def _resolve_uid(self, tempid_map: dict[str, str], uid: str | int) -> str:
        """Resolve a UID candidate using the tempid map.

        Parameters
        ----------
        tempid_map : dict[str, str]
            Mapping of temporary IDs to their resolved Roam UIDs.
        uid : str or int
            UID returned from the batch action (may be temporary).

        Returns
        -------
        str
            Resolved UID that should be stored in the database.

        Raises
        ------
        ValueError
            If an integer temp UID cannot be found in the response map.
        """
        if isinstance(uid, int):
            resolved = tempid_map.get(str(uid))
            if resolved is None:
                raise ValueError(f"Temp UID {uid} missing from Roam response")
            return resolved
        return tempid_map.get(uid, uid)

    def _upsert_page(
        self,
        existing_page: RoamPage | None,
        daily_note_uid: str,
        header_uid: str,
        export_batch: RoamExportBatch,
    ) -> RoamPage:
        """Insert or update the `RoamPage` record for the current daily note.

        Parameters
        ----------
        existing_page : RoamPage or None
            Previously stored page record, or ``None`` if one does not exist.
        daily_note_uid : str
            UID of the daily note page.
        header_uid : str
            Resolved UID for the highlights header block.
        export_batch : RoamExportBatch
            Batch that should be linked to the page.

        Returns
        -------
        RoamPage
            The page record that should be used for subsequent operations.
        """
        if existing_page is None:
            page = RoamPage(
                page_uid=daily_note_uid,
                highlights_header_uid=header_uid,
                highlights_header_text=self.highlights_header,
                export_batch=export_batch,
            )
            self._session.add(page)
            return page

        existing_page.highlights_header_uid = header_uid
        existing_page.highlights_header_text = self.highlights_header
        existing_page.export_batch = export_batch
        return existing_page

    def _add_staged_books_to_session(
        self,
        book_exports: list[StagedBookExport],
        tempid_map: dict[str, str],
        export_batch: RoamExportBatch,
    ) -> None:
        """
        Add staged book exports to the session using resolved UIDs.

        Parameters
        ----------
        book_exports : list[PendingBookExport]
            Pending book exports to persist.
        tempid_map : dict[str, str]
            Mapping of temporary IDs to resolved Roam UIDs.
        export_batch : RoamExportBatch
            Batch to associate with the persisted exports.

        """
        for export in book_exports:
            parent_uid = self._resolve_uid(tempid_map, export.temp_uid)
            self._session.add(
                RoamBookExport(
                    user_book_id=export.user_book_id,
                    page_uid=export.page_uid,
                    parent_block_uid=parent_uid,
                    export_batch=export_batch,
                )
            )

    def _add_staged_highlights_to_session(
        self,
        highlight_exports: list[StagedHighlightExport],
        tempid_map: dict[str, str],
        export_batch: RoamExportBatch,
    ) -> None:
        """
        Add staged highlight exports to the session using resolved UIDs.

        Parameters
        ----------
        highlight_exports : list[StagedHighlightExport]
            Staged highlight exports to persist.
        tempid_map : dict[str, str]
            Mapping of temporary IDs to resolved Roam UIDs.
        export_batch : RoamExportBatch
            Batch to associate with the persisted exports.

        """
        for export in highlight_exports:
            block_uid = self._resolve_uid(tempid_map, export.primary_temp_uid)
            self._session.add(
                RoamHighlightExport(
                    highlight_id=export.highlight_id,
                    page_uid=export.page_uid,
                    block_uid=block_uid,
                    export_date=export.export_date,
                    export_batch=export_batch,
                )
            )

    def _add_staged_highlight_snapshots_to_session(
        self,
        snapshots: list[StagedHighlightSnapshot],
        tempid_map: dict[str, str],
        export_batch: RoamExportBatch,
    ) -> None:
        """
        Add staged highlight snapshots to the session using resolved UIDs.

        Parameters
        ----------
        snapshots : list[StagedHighlightSnapshot]
            Staged highlight snapshots to persist.
        tempid_map : dict[str, str]
            Mapping of temporary IDs to resolved Roam UIDs.
        export_batch : RoamExportBatch
            Batch to associate with the persisted exports.

        """
        for snapshot_pending in snapshots:
            snapshot_tree = self._resolve_block_tree(
                snapshot_pending.block_tree, tempid_map
            )
            self._session.add(
                RoamHighlightSnapshot(
                    highlight_id=snapshot_pending.highlight_id,
                    block_tree=snapshot_tree,
                    block_tree_hash=self.stable_hash(snapshot_tree),
                    version=snapshot_pending.version,
                    created_at=datetime.now(),
                    export_batch=export_batch,
                )
            )

    #! Can't we just remove page, and then only create a page if it doesn't exist?
    def _create_page_snapshot(
        self,
        daily_note_uid: str,
        header_uid: str,
        page: RoamPage,
        export_batch: RoamExportBatch,
    ) -> None:
        """
        Create a new page snapshot by fetching the latest Roam block tree.

        Parameters
        ----------
        daily_note_uid : str
            UID of the daily note being exported.
        header_uid : str
            UID of the header block whose subtree should be pulled.
        page : RoamPage
            Page record that will own the snapshot.
        export_batch : RoamExportBatch
            Batch that should be associated with the snapshot.

        """
        block_tree = self.roam_client.fetch_block_subtree(header_uid)
        snapshot = RoamPageSnapshot(
            page_uid=daily_note_uid,
            block_tree=block_tree,
            block_tree_hash=self.stable_hash(block_tree),
            version=len(page.snapshots) + 1,
            version_date=datetime.now(),
            export_batch=export_batch,
        )
        self._session.add(snapshot)

    def _resolve_block_tree(
        self, block_tree: dict[str, Any], tempid_map: dict[str, str]
    ) -> dict[str, Any]:
        resolved_uid = self._resolve_uid(tempid_map, block_tree["uid"])
        resolved_children = [
            self._resolve_block_tree(child, tempid_map)
            for child in block_tree.get("children", [])
        ]
        resolved_tree = {
            **block_tree,
            "uid": resolved_uid,
            "children": resolved_children,
        }
        return resolved_tree

    def _get_existing_book_export(
        self, daily_note_uid: str, user_book_id: int
    ) -> RoamBookExport | None:
        """
        Fetch an existing book export for the specified page and book.

        Parameters
        ----------
        daily_note_uid : str
            UID of the daily note page.
        user_book_id : int
            Identifier of the book.

        Returns
        -------
        RoamBookExport | None
            Existing export record if present, otherwise `None`.
        """
        return (
            self._session.query(RoamBookExport)
            .filter_by(user_book_id=user_book_id, page_uid=daily_note_uid)
            .first()
        )

    def _get_existing_highlight_export(
        self, daily_note_uid: str, highlight_id: int
    ) -> RoamHighlightExport | None:
        """
        Fetch an existing highlight export for the specified page and highlight.

        Parameters
        ----------
        daily_note_uid : str
            UID of the daily note page.
        highlight_id : int
            Identifier of the highlight.

        Returns
        -------
        RoamHighlightExport | None
            Existing export record if present, otherwise `None`.
        """
        return (
            self._session.query(RoamHighlightExport)
            .filter_by(highlight_id=highlight_id, page_uid=daily_note_uid)
            .first()
        )

    def _get_last_highlight_snapshot(
        self, highlight_id: int
    ) -> RoamHighlightSnapshot | None:
        """
        Fetch the most recent snapshot for a highlight.

        Parameters
        ----------
        highlight_id : int
            Identifier of the highlight whose snapshots should be inspected.

        Returns
        -------
        RoamHighlightSnapshot | None
            Most recent snapshot instance, or `None` if none exist.
        """
        return (
            self._session.query(RoamHighlightSnapshot)
            .filter_by(highlight_id=highlight_id)
            .order_by(RoamHighlightSnapshot.version.desc())
            .first()
        )


if __name__ == "__main__":
    r = RoamDailyNoteHighlightWriter(batch_id=3)
    # Batch 3 has two daily notes: 15th July and 14th August
    # Batch 8 has one: 7th September
    r.write_batch_to_daily_notes()
