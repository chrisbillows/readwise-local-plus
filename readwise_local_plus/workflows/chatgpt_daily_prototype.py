from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
import logging
import re
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from tldextract import extract

from readwise_local_plus.config import fetch_user_config
from readwise_local_plus.db_operations import get_session
from readwise_local_plus.integrations.roam import RoamClient, TempUidGenerator
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

READWISE_HEADER = "[[Readwise highlights]]"
READWISE_LINKS = "__Readwise Links__"
ActionKind = Literal[
    "readwise_header",
    "book_header",
    "book_sub_header",
    "highlight",
    "note",
    "links_header",
    "book_link_header",
    "book_link",
]


def strip_markdown_links(s: str) -> str:
    return re.sub(r"(?<!\!)\[([^\]]+)\]\([^)]+\)", r"\1", s)


@dataclass
class DNHighlight:
    user_book_id: int
    id: int
    text: str
    note: str | None
    location: int | None
    created_at: datetime | None
    updated_at: datetime | None
    url: str | None
    readwise_url: str | None

    @property
    def roam_highlight(self) -> str:
        return strip_markdown_links(self.text.strip().replace("\n", ""))

    @property
    def roam_note(self) -> str:
        return self.note.strip().replace("\n", "") if self.note else ""


@dataclass
class DNBook:
    user_book_id: int
    title: str
    author: str
    readable_title: str
    source: str
    unique_url: str
    category: str
    readwise_url: str
    source_url: str
    highlights: list[DNHighlight] = field(default_factory=list)

    @property
    def roam_book_header(self) -> str:
        clean_title = self.readable_title.strip().replace("\n", "")

        if self.category == "tweets":
            if not clean_title.lower().startswith("tweets from") and self.author:
                if self.author.startswith("@"):
                    author = self.author.split(" ")[0][1:] if self.author else "unknown"
                else:
                    author = self.author.title()
                clean_title = f"Tweet Thread From {author}"

        return clean_title

    @property
    def roam_sub_header(self) -> str:
        sub_header = "#[[rw]]"

        if self.category == "tweets":
            sub_header += " #[[tweets]]"

        elif self.category == "articles":
            sub_header += " #[[articles]]"

            author = self.author.title() if self.author else None
            if author:
                sub_header += f" #[[{author}]]"

            if isinstance(self.source_url, str):
                try:
                    domain = extract(self.source_url).top_domain_under_public_suffix
                    if domain:
                        sub_header += f" #[[{domain.lower()}]]"
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug(
                        "Failed to extract domain from %s: %s",
                        self.source_url,
                        exc,
                    )

        return sub_header

    @property
    def roam_links(self) -> str:
        rw_link = self.readwise_url
        rw_reader_link = self.unique_url if self.unique_url else None

        links = f"[rw]({rw_link})"

        if self.category == "articles":
            links += f" [source]({self.source_url})"

        if self.category == "tweets" and self.highlights:
            links += f" [source]({self.highlights[0].url})"

        if rw_reader_link:
            links += f" [rwr]({rw_reader_link})"

        return links


class DNHighlightsPayload:
    """
    Build daily note payload:
    dict[date] -> list[DNBook]
    """

    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        self._session: Session = get_session(fetch_user_config().db_path)
        self.grouped: dict[date, dict[int, DNBook]] = defaultdict(dict)

    def build(self) -> dict[date, list[DNBook]]:
        logger.info("Create payload for batch: %s", self.batch_id)

        rows = self._fetch()

        for row in rows:
            self._process_row(row)

        self._session.close()

        return {d: list(books.values()) for d, books in self.grouped.items()}

    def _fetch(self) -> list[Highlight]:
        stmt = (
            select(Highlight)
            .join(Highlight.book)
            .where(
                Highlight.batch_id == self.batch_id,
                Book.category.in_(["articles", "tweets"]),
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

    def _process_row(self, h: Highlight) -> None:
        date_key = h.created_at.date()
        book_id = h.book.user_book_id

        if book_id not in self.grouped[date_key]:
            self.grouped[date_key][book_id] = DNBook(
                user_book_id=book_id,
                title=h.book.title,
                author=h.book.author,
                readable_title=h.book.readable_title,
                source=h.book.source,
                category=h.book.category,
                unique_url=h.book.unique_url,
                readwise_url=h.book.readwise_url,
                source_url=h.book.source_url,
            )

        self.grouped[date_key][book_id].highlights.append(
            DNHighlight(
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


@dataclass
class ExistingDNState:
    """
    Known state of a single daily note, sourced from db.

    Attributes
    ----------
    page_uid : str
        The roam daily note uid e.g. the date in "MM-DD-YYYY".
    page_exists : bool
        If the page is known to exist.
    rw_header_uid : str | None
        The roam block uid if the header has already been written, else None.
    book_header_uids : dict[int, str]
        A dict of existing book headers where the key is the 'user_book_id' and the
        value is the roam block uid. Will be an empty dict if no book headers exist. 
    highlight_ids : set[int] 
        A set of Readwise highlight 'id' already exported for this page. Will be an 
        empty set if no highlights exist. 
        NOTE: Stores ids only. We never use highlights as parents for new objects 
        (i.e. a new note on an existing highlight is currently not written).
    """
    page_uid: str
    page_exists: bool
    rw_header_uid: str | None
    book_header_uids: dict[int, str]
    highlight_ids: set[int]


@dataclass
class RoamBatchAction:
    kind: ActionKind
    body: dict[str, Any]
    uid: str | int
    page_uid: str
    user_book_id: int | None = None
    highlight_id: int | None = None
    is_primary_highlight: bool = False
    block_tree: dict[str, Any] | None = None
    resolved_uid: str | None = None
    export_date: datetime = field(default_factory=datetime.now)

    @property
    def is_temp_uid(self) -> bool:
        return isinstance(self.uid, int)

    def resolve(self, tempid_map: dict[str, str]) -> None:
        if self.is_temp_uid:
            resolved = tempid_map.get(str(self.uid))
            if resolved is None:
                raise ValueError(f"Temp UID {self.uid} missing from Roam response")
            self.resolved_uid = resolved
        else:
            self.resolved_uid = str(self.uid)


@dataclass
class RoamBatchActionList:
    actions: list[RoamBatchAction] = field(default_factory=list)

    @property
    def batch_action_body(self) -> dict[str, Any]:
        return {
            "action": "batch-actions",
            "actions": [action.body for action in self.actions],
        }

    def append(self, action: RoamBatchAction) -> None:
        self.actions.append(action)

    def resolve(self, tempid_map: dict[str, str]) -> None:
        for action in self.actions:
            action.resolve(tempid_map)


@dataclass
class HighlightRenderResult:
    primary_uid: str | int
    block_tree: dict[str, Any]


@dataclass
class DailyNoteExportResult:
    target_date: date
    page_uid: str
    rw_header_uid: str | None
    content_actions: RoamBatchActionList
    link_actions: RoamBatchActionList


class DNExporterPrototype:
    """
    Prototype exporter that keeps the refactor's flow but stores write intent and
    export metadata together on action objects instead of using mutable state flags.
    """

    def __init__(self, grouped_highlights: dict[date, list[DNBook]]) -> None:
        self.grouped_highlights = grouped_highlights
        self._uid_gen = TempUidGenerator()
        self._rc = RoamClient()
        self._session: Session = get_session(fetch_user_config().db_path)

    def export(self) -> list[DailyNoteExportResult]:
        logger.info("Exporting...")
        results: list[DailyNoteExportResult] = []

        for target_date, books in self.grouped_highlights.items():
            logger.info("To daily note: %s", target_date.isoformat())
            results.append(self._export_daily_note(target_date, books))

        self._session.close()
        return results

    def _export_daily_note(
        self,
        target_date: date,
        books: list[DNBook],
    ) -> DailyNoteExportResult:
        state = self._load_existing_state(target_date, books)
        self._ensure_daily_note(target_date, state)

        batch_actions = self._build_content_actions(state, books)
        write_response = self._execute_batch_actions(batch_actions)
        batch_actions.resolve(write_response.get("tempids-to-uids", {}))

        link_actions = self._build_link_actions(state, books, batch_actions)
        if link_actions.actions:
            write_response = self._execute_batch_actions(link_actions)
            link_actions.resolve(write_response.get("tempids-to-uids", {}))

        return DailyNoteExportResult(
            target_date=target_date,
            page_uid=state.page_uid,
            rw_header_uid=state.rw_header_uid,
            content_actions=batch_actions,
            link_actions=link_actions,
        )

    def _load_existing_state(
        self, target_date: date, books: list[DNBook]
    ) -> ExistingDNState:
        page_uid = self._rc.date_to_roam_daily_note(target_date)
        tracked_page = self._session.get(RoamPage, page_uid)
        known_page = self._session.get(RoamKnownPage, page_uid)

        book_exports = {
            row.user_book_id: row.parent_block_uid
            for row in self._session.query(RoamBookExport).filter_by(page_uid=page_uid)
        }

        highlight_ids = {
            row.highlight_id
            for row in self._session.query(RoamHighlightExport).filter_by(page_uid=page_uid)
        }

        return ExistingDNState(
            page_uid=page_uid,
            page_exists=(known_page is not None or tracked_page is not None),
            rw_header_uid=(
                tracked_page.highlights_header_uid if tracked_page is not None else None
            ),
            book_header_uids=book_exports,
            highlight_ids=highlight_ids,
        )

    def _ensure_daily_note(
        self, target_date: date, state: ExistingDNState
    ) -> None:
        if state.page_exists:
            return

        dn_long = self._rc._format_daily_note_title_long_format(target_date)
        try:
            self._rc.create_page(dn_long, exists_ok=True)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to ensure daily note %s exists: %s", state.page_uid, exc)

        self._session.add(
            RoamKnownPage(page_uid=state.page_uid, last_verified_at=datetime.now())
        )
        self._session.flush()

    def _build_content_actions(
        self,
        state: ExistingDNState,
        books: list[DNBook],
    ) -> RoamBatchActionList:
        actions = RoamBatchActionList()

        if state.rw_header_uid is not None:
            header_uid = state.rw_header_uid
        else:
            header_uid = self._append_action(
                actions=actions,
                kind="readwise_header",
                parent_uid=state.page_uid,
                content=READWISE_HEADER,
                page_uid=state.page_uid,
                heading=1,
            )

        for book in books:
            logger.info("Book: %s", book.readable_title[:40])

            existing_book = state.book_header_uids.get(book.user_book_id)
            if existing_book is not None:
                book_header_uid = existing_book
            else:
                book_header_uid = self._append_action(
                    actions=actions,
                    kind="book_header",
                    parent_uid=header_uid,
                    content=book.roam_book_header,
                    page_uid=state.page_uid,
                    user_book_id=book.user_book_id,
                    heading=3,
                )

            sub_header_uid = self._append_action(
                actions=actions,
                kind="book_sub_header",
                parent_uid=book_header_uid,
                content=book.roam_sub_header,
                page_uid=state.page_uid,
                user_book_id=book.user_book_id,
            )

            for hl in book.highlights:
                if hl.id in state.highlight_ids:
                    continue

                render_result = self._render_highlight(
                    actions=actions,
                    page_uid=state.page_uid,
                    parent_uid=sub_header_uid,
                    highlight=hl,
                )

                for action in actions.actions:
                    if action.highlight_id == hl.id and action.is_primary_highlight:
                        action.block_tree = render_result.block_tree
                        break

        return actions

    def _build_link_actions(
        self,
        state: ExistingDNState,
        books: list[DNBook],
        content_actions: RoamBatchActionList,
    ) -> RoamBatchActionList:
        actions = RoamBatchActionList()
        child_blocks = self._rc.fetch_child_blocks(state.page_uid) or []
        links_header_uid = self._find_existing_child_uid(child_blocks, READWISE_LINKS)

        if links_header_uid is None:
            links_header_uid = self._append_action(
                actions=actions,
                kind="links_header",
                parent_uid=state.page_uid,
                content=READWISE_LINKS,
                page_uid=state.page_uid,
            )

        existing_link_children: list[dict[str, str]] = []
        if not isinstance(links_header_uid, int):
            existing_link_children = self._rc.fetch_child_blocks(links_header_uid) or []

        for book in books:
            book_uid = self._resolve_book_uid(
                state=state,
                content_actions=content_actions,
                user_book_id=book.user_book_id,
            )
            book_link_header = f"(({book_uid}))"
            existing_link_uid = self._find_existing_child_uid(
                existing_link_children, book_link_header
            )

            if existing_link_uid is None:
                existing_link_uid = self._append_action(
                    actions=actions,
                    kind="book_link_header",
                    parent_uid=links_header_uid,
                    content=book_link_header,
                    page_uid=state.page_uid,
                    user_book_id=book.user_book_id,
                )

            self._append_action(
                actions=actions,
                kind="book_link",
                parent_uid=existing_link_uid,
                content=book.roam_links,
                page_uid=state.page_uid,
                user_book_id=book.user_book_id,
            )

        return actions

    def _append_action(
        self,
        actions: RoamBatchActionList,
        kind: ActionKind,
        parent_uid: str | int,
        content: str,
        page_uid: str,
        *,
        user_book_id: int | None = None,
        highlight_id: int | None = None,
        is_primary_highlight: bool = False,
        heading: int | None = None,
    ) -> str | int:
        uid = self._uid_gen.next()
        block: dict[str, Any] = {"string": content, "uid": uid}
        if heading is not None:
            block["heading"] = heading

        body = {
            "action": "create-block",
            "location": {"order": "last", "parent-uid": parent_uid},
            "block": block,
        }

        actions.append(
            RoamBatchAction(
                kind=kind,
                body=body,
                uid=uid,
                page_uid=page_uid,
                user_book_id=user_book_id,
                highlight_id=highlight_id,
                is_primary_highlight=is_primary_highlight,
            )
        )
        return uid

    def _render_highlight(
        self,
        actions: RoamBatchActionList,
        page_uid: str,
        parent_uid: str | int,
        highlight: DNHighlight,
    ) -> HighlightRenderResult:
        highlight_uid = self._append_action(
            actions=actions,
            kind="highlight",
            parent_uid=parent_uid,
            content=highlight.roam_highlight,
            page_uid=page_uid,
            highlight_id=highlight.id,
            user_book_id=highlight.user_book_id,
            is_primary_highlight=True,
        )

        children: list[dict[str, Any]] = []
        if highlight.roam_note:
            note_uid = self._append_action(
                actions=actions,
                kind="note",
                parent_uid=highlight_uid,
                content=highlight.roam_note,
                page_uid=page_uid,
                highlight_id=highlight.id,
                user_book_id=highlight.user_book_id,
            )
            children.append(
                {
                    "uid": note_uid,
                    "text": highlight.roam_note,
                    "order": None,
                    "children": [],
                }
            )

        return HighlightRenderResult(
            primary_uid=highlight_uid,
            block_tree={
                "uid": highlight_uid,
                "text": highlight.roam_highlight,
                "order": None,
                "children": children,
            },
        )

    def _execute_batch_actions(self, actions: RoamBatchActionList) -> dict[str, Any]:
        if not actions.actions:
            return {}
        return self._rc._write(actions.batch_action_body) or {}

    def _resolve_book_uid(
        self,
        state: ExistingDNState,
        content_actions: RoamBatchActionList,
        user_book_id: int,
    ) -> str:
        existing_book = state.book_header_uids.get(user_book_id)
        if existing_book is not None:
            return existing_book

        for action in content_actions.actions:
            if action.kind == "book_header" and action.user_book_id == user_book_id:
                if action.resolved_uid is None:
                    raise ValueError(f"Book action for {user_book_id} was not resolved")
                return action.resolved_uid

        raise ValueError(f"No book UID found for {user_book_id}")

    @staticmethod
    def _find_existing_child_uid(
        child_blocks: list[dict[str, str]], content: str
    ) -> str | None:
        for block in child_blocks:
            block_content = list(block.keys())[0]
            if block_content == content:
                return list(block.values())[0]
        return None


class DNExportWriteback:
    """
    Persist the local SQLite record of a completed daily note export.
    """

    def __init__(self, roam_client: RoamClient) -> None:
        self._session: Session = get_session(fetch_user_config().db_path)
        self._roam_client = roam_client

    def persist(
        self,
        result: DailyNoteExportResult,
        export_batch: RoamExportBatch,
    ) -> None:
        page = self._upsert_page_row(result, export_batch)
        self._persist_content_rows(result.content_actions, export_batch)
        self._create_page_snapshot(
            page_uid=result.page_uid,
            header_uid=page.highlights_header_uid,
            page=page,
            export_batch=export_batch,
        )

    def persist_many(
        self,
        results: list[DailyNoteExportResult],
    ) -> None:
        export_batch = RoamExportBatch(database_write_time=datetime.now())
        self._session.add(export_batch)
        for result in results:
            self.persist(result, export_batch)
        self._session.commit()
        self._session.close()

    def _upsert_page_row(
        self,
        result: DailyNoteExportResult,
        export_batch: RoamExportBatch,
    ) -> RoamPage:
        tracked_page = self._session.get(RoamPage, result.page_uid)
        header_action = next(
            (
                action
                for action in result.content_actions.actions
                if action.kind == "readwise_header"
            ),
            None,
        )
        header_uid = (
            header_action.resolved_uid
            if header_action is not None
            else result.rw_header_uid
        )

        if tracked_page is None:
            page = RoamPage(
                page_uid=result.page_uid,
                highlights_header_uid=header_uid,
                highlights_header_text=READWISE_HEADER,
                export_batch=export_batch,
            )
            self._session.add(page)
            return page

        tracked_page.highlights_header_uid = header_uid
        tracked_page.highlights_header_text = READWISE_HEADER
        tracked_page.export_batch = export_batch
        return tracked_page

    def _persist_content_rows(
        self,
        content_actions: RoamBatchActionList,
        export_batch: RoamExportBatch,
    ) -> None:
        for action in content_actions.actions:
            if action.kind == "book_header" and action.user_book_id is not None:
                self._session.add(
                    RoamBookExport(
                        user_book_id=action.user_book_id,
                        page_uid=action.page_uid,
                        parent_block_uid=action.resolved_uid,
                        export_date=action.export_date,
                        export_batch=export_batch,
                    )
                )

            elif (
                action.kind == "highlight"
                and action.highlight_id is not None
                and action.is_primary_highlight
            ):
                self._session.add(
                    RoamHighlightExport(
                        highlight_id=action.highlight_id,
                        page_uid=action.page_uid,
                        block_uid=action.resolved_uid,
                        export_date=action.export_date,
                        export_batch=export_batch,
                    )
                )

                if action.block_tree is not None:
                    snapshot_tree = self._resolve_block_tree(
                        action.block_tree,
                        content_actions,
                    )
                    snapshot_version = self._get_next_highlight_snapshot_version(
                        action.highlight_id
                    )
                    self._session.add(
                        RoamHighlightSnapshot(
                            highlight_id=action.highlight_id,
                            block_tree=snapshot_tree,
                            block_tree_hash=self.stable_hash(snapshot_tree),
                            version=snapshot_version,
                            created_at=datetime.now(),
                            export_batch=export_batch,
                        )
                    )

    def _get_next_highlight_snapshot_version(self, highlight_id: int) -> int:
        latest_snapshot = (
            self._session.query(RoamHighlightSnapshot)
            .filter_by(highlight_id=highlight_id)
            .order_by(RoamHighlightSnapshot.version.desc())
            .first()
        )
        return (latest_snapshot.version + 1) if latest_snapshot is not None else 1

    def _create_page_snapshot(
        self,
        page_uid: str,
        header_uid: str,
        page: RoamPage,
        export_batch: RoamExportBatch,
    ) -> None:
        block_tree = self._roam_client.fetch_block_subtree(header_uid)
        self._session.add(
            RoamPageSnapshot(
                page_uid=page_uid,
                block_tree=block_tree,
                block_tree_hash=self.stable_hash(block_tree),
                version=len(page.snapshots) + 1,
                version_date=datetime.now(),
                export_batch=export_batch,
            )
        )

    def _resolve_block_tree(
        self,
        block_tree: dict[str, Any],
        actions: RoamBatchActionList,
    ) -> dict[str, Any]:
        resolved_uid = self._resolve_uid_from_actions(block_tree["uid"], actions)
        children = [
            self._resolve_block_tree(child, actions)
            for child in block_tree.get("children", [])
        ]
        return {
            **block_tree,
            "uid": resolved_uid,
            "children": children,
        }

    @staticmethod
    def stable_hash(obj: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(obj, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _resolve_uid_from_actions(
        uid: str | int, actions: RoamBatchActionList
    ) -> str:
        if isinstance(uid, str):
            return uid

        for action in actions.actions:
            if action.uid == uid:
                if action.resolved_uid is None:
                    raise ValueError(f"UID {uid} was not resolved")
                return action.resolved_uid

        raise ValueError(f"UID {uid} not found in action list")


def main() -> None:
    dnhp = DNHighlightsPayload(60)
    grouped_highlights = dnhp.build()
    exporter = DNExporterPrototype(grouped_highlights)
    results = exporter.export()
    writeback = DNExportWriteback(exporter._rc)
    writeback.persist_many(results)


if __name__ == "__main__":
    main()
