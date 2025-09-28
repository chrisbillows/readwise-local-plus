"""
Fetch highlights based on a ReadwiseBatch id and write them to a Roam daily note.

The daily note will be the `created_at` date of the last highlight in the container book
object.

Currently only tweets and articles (hardcoded) are actioned.

"""

import hashlib
import json
from collections import defaultdict
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

# Highlights are written, by book, underneath this header. Only one header will be
# added by daily note. No distinction is made by batch, and no ordering under the
# header is enforced.
HIGHLIGHTS_HEADER = "[[Readwise highlights]]"


class RoamDailyNoteHighlightWriter:
    def __init__(self, highlights_header: str) -> None:
        """Object init."""
        self.roam_client = RoamClient()
        self.highlights_header = highlights_header
        self.highlights: dict[date, dict[Book, list[Highlight]]] = defaultdict(dict)

    def write_batch_to_daily_notes(self, batch_id: int) -> None:
        """
        Driver method.
        """
        self._session: Session = get_session(fetch_user_config().db_path)
        self.fetch_highlights(batch_id)
        self._write_highlights()
        self._session.close()

    def fetch_highlights(self, batch_id: int) -> None:
        """
        Fetch highlights for a batch, filtered for tweets & articles, grouped by
        daily note date → book_id → highlights.
        """
        stmt = (
            select(Highlight)
            .join(Highlight.book)
            .where(
                Highlight.batch_id == batch_id,
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

    @staticmethod
    def stable_hash(obj: dict[str, Any]) -> str:
        """Return a stable SHA256 hash for a JSON-serializable object."""
        # sort_keys=True ensures deterministic ordering
        return hashlib.sha256(
            json.dumps(obj, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _write_highlights(self) -> None:
        """Write fetched highlights to Roam daily notes."""
        if not self.highlights:
            return

        export_batch = RoamExportBatch(database_write_time=datetime.now())
        self._session.add(export_batch)

        for daily_note, books_and_highlights in self.highlights.items():
            daily_note_uid = self.roam_client.date_to_roam_daily_note(daily_note)

            existing_page = self._session.get(RoamPage, daily_note_uid)
            roam_batch_action = RoamBatchAction()

            header_uid_candidate: str | int
            if existing_page:
                header_uid_candidate = existing_page.highlights_header_uid
            else:
                header_uid_candidate = roam_batch_action.append_a_child_block_action(
                    daily_note_uid,
                    self.highlights_header,
                    heading=1,
                    open=True,
                )

            pending_book_exports: list[dict[str, Any]] = []
            pending_highlight_exports: list[dict[str, Any]] = []
            pending_highlight_snapshots: list[dict[str, Any]] = []

            for book, highlights in books_and_highlights.items():
                existing_book_export = (
                    self._session.query(RoamBookExport)
                    .filter_by(user_book_id=book.user_book_id, page_uid=daily_note_uid)
                    .first()
                )

                book_block_uid_candidate: str | int
                if existing_book_export:
                    book_block_uid_candidate = existing_book_export.parent_block_uid
                else:
                    # book_header = f"{book.title} #{book.author} "

                    book_block_uid_candidate = (
                        roam_batch_action.append_a_child_block_action(
                            header_uid_candidate,
                            book.title if book.title else "[ERROR]: Missing title",
                            heading=3,
                        )
                    )
                    pending_book_exports.append(
                        {
                            "user_book_id": book.user_book_id,
                            "page_uid": daily_note_uid,
                            "temp_uid": book_block_uid_candidate,
                        }
                    )

                for hl in highlights:
                    existing_export = (
                        self._session.query(RoamHighlightExport)
                        .filter_by(highlight_id=hl.id, page_uid=daily_note_uid)
                        .first()
                    )
                    if existing_export:
                        continue

                    hl_temp_uid = roam_batch_action.append_a_child_block_action(
                        book_block_uid_candidate,
                        hl.text,
                    )
                    pending_highlight_exports.append(
                        {
                            "highlight_id": hl.id,
                            "page_uid": daily_note_uid,
                            "temp_uid": hl_temp_uid,
                            "export_date": datetime.now(),
                        }
                    )

                    last_snapshot = (
                        self._session.query(RoamHighlightSnapshot)
                        .filter_by(highlight_id=hl.id)
                        .order_by(RoamHighlightSnapshot.version.desc())
                        .first()
                    )
                    next_version = (last_snapshot.version + 1) if last_snapshot else 1

                    block_tree = {
                        "uid": hl_temp_uid,
                        "text": hl.text,
                        "order": None,
                        "children": [],
                    }
                    pending_highlight_snapshots.append(
                        {
                            "highlight_id": hl.id,
                            "temp_uid": hl_temp_uid,
                            "block_tree": block_tree,
                            "version": next_version,
                        }
                    )

            actions = roam_batch_action.batch_action_body["actions"]
            tempid_map = (
                roam_batch_action.execute_batch_action() if actions else {}
            ) or {}

            def resolve_uid(uid: str | int) -> str:
                if isinstance(uid, int):
                    resolved = tempid_map.get(str(uid))
                    if resolved is None:
                        raise ValueError(f"Temp UID {uid} missing from Roam response")
                    return resolved
                return tempid_map.get(uid, uid)

            header_uid = resolve_uid(header_uid_candidate)

            if not existing_page:
                existing_page = RoamPage(
                    page_uid=daily_note_uid,
                    highlights_header_uid=header_uid,
                    highlights_header_text=self.highlights_header,
                    export_batch=export_batch,
                )
                self._session.add(existing_page)
            else:
                existing_page.highlights_header_uid = header_uid
                existing_page.highlights_header_text = self.highlights_header
                existing_page.export_batch = export_batch

            for export in pending_book_exports:
                parent_uid = resolve_uid(export["temp_uid"])
                self._session.add(
                    RoamBookExport(
                        user_book_id=export["user_book_id"],
                        page_uid=export["page_uid"],
                        parent_block_uid=parent_uid,
                        export_batch=export_batch,
                    )
                )

            for export in pending_highlight_exports:
                block_uid = resolve_uid(export["temp_uid"])
                self._session.add(
                    RoamHighlightExport(
                        highlight_id=export["highlight_id"],
                        page_uid=export["page_uid"],
                        block_uid=block_uid,
                        export_date=export["export_date"],
                        export_batch=export_batch,
                    )
                )

            for snapshot_d in pending_highlight_snapshots:
                block_uid = resolve_uid(snapshot_d["temp_uid"])
                snapshot_tree = snapshot_d["block_tree"]
                snapshot_tree["uid"] = block_uid
                self._session.add(
                    RoamHighlightSnapshot(
                        highlight_id=snapshot_d["highlight_id"],
                        block_tree=snapshot_tree,
                        block_tree_hash=self.stable_hash(snapshot_tree),
                        version=snapshot_d["version"],
                        created_at=datetime.now(),
                        export_batch=export_batch,
                    )
                )

            block_tree = self.roam_client.fetch_block_subtree(header_uid)
            snapshot = RoamPageSnapshot(
                page_uid=daily_note_uid,
                block_tree=block_tree,
                block_tree_hash=self.stable_hash(block_tree),
                version=len(existing_page.snapshots) + 1,
                version_date=datetime.now(),
                export_batch=export_batch,
            )
            self._session.add(snapshot)

        self._session.commit()


if __name__ == "__main__":
    r = RoamDailyNoteHighlightWriter("Delete Me")
    # Batch 3 has two daily notes: 15th July and 14th August
    # Batch 8 has one: 7th September
    r.write_batch_to_daily_notes(batch_id=3)
