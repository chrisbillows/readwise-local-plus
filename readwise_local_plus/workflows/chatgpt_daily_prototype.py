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

    @property
    def roam_highlight(self) -> str:
        return strip_markdown_links(self.text.strip().replace("\n", ""))

    @property
    def roam_note(self) -> str:
        return self.note.strip().replace("\n", "") if self.note else ""


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


class DbData:
    """
    Build daily note payload:
    dict[date] -> list[DNBook]
    """

    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        self._session: Session = get_session(fetch_user_config().db_path)
        self.grouped: dict[date, dict[int, BookFromDb]] = defaultdict(dict)

    def build(self) -> dict[date, list[BookFromDb]]:
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
            self.grouped[date_key][book_id] = BookFromDb(
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


@dataclass
class DbDNState:
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
class RoamExportNode:
    kind: ActionKind
    body: dict[str, Any]
    uid: str | int
    parent_uid: str | int
    page_uid: str
    user_book_id: int | None = None
    highlight_id: int | None = None
    resolved_uid: str | None = None
    resolved_parent_uid: str | None = None
    export_date: datetime = field(default_factory=datetime.now)

    def resolve(self, tempid_map: dict[str, str]) -> None:
        if isinstance(self.uid, int):
            resolved = tempid_map.get(str(self.uid))
            if resolved is None:
                raise ValueError(f"Temp UID {self.uid} missing from Roam response")
            self.resolved_uid = resolved
        else:
            self.resolved_uid = self.uid

        if isinstance(self.parent_uid, int):
            resolved_parent = tempid_map.get(str(self.parent_uid))
            if resolved_parent is None:
                raise ValueError(
                    f"Temp parent UID {self.parent_uid} missing from Roam response"
                )
            self.resolved_parent_uid = resolved_parent
        else:
            self.resolved_parent_uid = self.parent_uid


class RoamExportNodeBuilder:
    def __init__(self, page_uid: str) -> None:
        self.page_uid = page_uid
        self._uid_gen = TempUidGenerator()

    def instantiate_node(
        self,
        kind: ActionKind,
        parent_uid: str | int,
        content: str,
        heading: int | None = None,
        user_book_id: int | None = None,
        highlight_id: int | None = None,
    ) -> RoamExportNode:
        uid = self._uid_gen.next()
        block: dict[str, Any] = {"string": content, "uid": uid}
        if heading is not None:
            block["heading"] = heading

        return RoamExportNode(
            kind=kind,
            body={
                "action": "create-block",
                "location": {"order": "last", "parent-uid": parent_uid},
                "block": block,
            },
            uid=uid,
            parent_uid=parent_uid,
            page_uid=self.page_uid,
            user_book_id=user_book_id,
            highlight_id=highlight_id,
        )

class DNExporter:
    def __init__(
        self,
        target_date: date,
        books: list[BookFromDb],
        roam_client: RoamClient,
        session: Session,
    ) -> None:
        self.target_date = target_date
        self.books = books
        self._rc = roam_client
        self._session = session
        self.state = self._load_existing_state()
        self.node_builder = RoamExportNodeBuilder(self.state.page_uid)
        self.hl_re_nodes: list[RoamExportNode] = []
        self.link_re_nodes: list[RoamExportNode] = []
        self.target_re_nodes: list[RoamExportNode] | None = None

    def export(self) -> tuple[list[RoamExportNode], list[RoamExportNode]]:
        self._ensure_daily_note()

        self.target_re_nodes = self.hl_re_nodes
        self._build_hl_roam_export_nodes()
        batch_action_body = {
            "action": "batch-actions",
            "actions": [node.body for node in self.hl_re_nodes],
        }
        roam_api_response = self._rc._write(batch_action_body)
        tempid_map = roam_api_response.get("tempids-to-uids", {})
        for re_node in self.hl_re_nodes:
            re_node.resolve(tempid_map)

        self.target_re_nodes = self.link_re_nodes
        self._build_link_roam_export_nodes()
        batch_action_body = {
            "action": "batch-actions",
            "actions": [node.body for node in self.link_re_nodes],
        }
        roam_api_response = self._rc._write(batch_action_body)
        tempid_map = roam_api_response.get("tempids-to-uids", {})
        for re_node in self.link_re_nodes:
            re_node.resolve(tempid_map)

        return self.hl_re_nodes, self.link_re_nodes
    
    def _build_hl_roam_export_nodes(self) -> None:
        if self.state.rw_header_uid is not None:
            header_uid = self.state.rw_header_uid
        else:
            rw_header_node = self.node_builder.instantiate_node(
                "readwise_header", self.state.page_uid, READWISE_HEADER, 1
            )
            self.target_re_nodes.append(rw_header_node)
            header_uid = rw_header_node.uid

        for book in self.books:
            logger.info("Book: %s", book.readable_title[:40])

            existing_book = self.state.book_header_uids.get(book.user_book_id)
            if existing_book is not None:
                book_header_uid = existing_book
            else:
                book_header_node = self.node_builder.instantiate_node(
                    "book_header",
                    header_uid,
                    book.roam_book_header,
                    3,
                    book.user_book_id,
                )
                self.target_re_nodes.append(book_header_node)
                book_header_uid = book_header_node.uid

            book_sub_header_node = self.node_builder.instantiate_node(
                "book_sub_header",
                book_header_uid,
                book.roam_sub_header,
                None,
                book.user_book_id,
            )
            self.target_re_nodes.append(book_sub_header_node)
            sub_header_uid = book_sub_header_node.uid

            for hl in book.highlights:
                if hl.id in self.state.highlight_ids:
                    continue

                highlight_node = self.node_builder.instantiate_node(
                    "highlight",
                    sub_header_uid,
                    hl.roam_highlight,
                    None,
                    hl.user_book_id,
                    hl.id,
                )
                self.target_re_nodes.append(highlight_node)

                if hl.roam_note:
                    note_node = self.node_builder.instantiate_node(
                        "note",
                        highlight_node.uid,
                        hl.roam_note,
                        None,
                        hl.user_book_id,
                        hl.id,
                    )
                    self.target_re_nodes.append(note_node)

    def _build_link_roam_export_nodes(self) -> None:
        # Link headers are not yet stored in db. Fetch the live page tree once and
        # inspect it locally to avoid multiple Roam API reads.
        page_tree = self._rc.fetch_block_subtree(self.state.page_uid) or {}
        page_children = page_tree.get("children", [])
        links_header_uid, header_children = self._get_or_create_child(
            page_children, self.state.page_uid, READWISE_LINKS, "links_header",
        )

        for book in self.books:
            book_uid = self._resolve_book_uid(book.user_book_id)
            book_link_header = f"(({book_uid}))"
            book_link_header_uid, _ = self._get_or_create_child(
                header_children, links_header_uid,
                book_link_header,
                "book_link_header",
                book.user_book_id,
            )

            book_link_node = self.node_builder.instantiate_node(
                "book_link",
                book_link_header_uid,
                book.roam_links,
                None,
                book.user_book_id,
            )
            self.target_re_nodes.append(book_link_node)

    def _load_existing_state(self) -> DbDNState:
        page_uid = self._rc.date_to_roam_daily_note(self.target_date)
        existing_page = self._session.get(RoamPage, page_uid)
        known_page = self._session.get(RoamKnownPage, page_uid)

        existing_book_header_uids = {
            row.user_book_id: row.parent_block_uid
            for row in self._session.query(RoamBookExport).filter_by(page_uid=page_uid)
        }

        highlight_ids = {
            row.highlight_id
            for row in self._session.query(RoamHighlightExport).filter_by(page_uid=page_uid)
        }

        return DbDNState(
            page_uid=page_uid,
            page_exists=(known_page is not None or existing_page is not None),
            rw_header_uid=(
                existing_page.highlights_header_uid if existing_page is not None else None
            ),
            book_header_uids=existing_book_header_uids,
            highlight_ids=highlight_ids,
        )

    def _ensure_daily_note(self) -> None:
        if self.state.page_exists:
            return

        dn_long = self._rc._format_daily_note_title_long_format(self.target_date)
        try:
            self._rc.create_page(dn_long, exists_ok=True)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to ensure daily note %s exists: %s", self.state.page_uid, exc
            )
            return

        self._session.add(
            RoamKnownPage(page_uid=self.state.page_uid, last_verified_at=datetime.now())
        )
        self._session.flush()

    def _resolve_book_uid(self, user_book_id: int) -> str:
        existing_book = self.state.book_header_uids.get(user_book_id)
        if existing_book is not None:
            return existing_book

        for node in self.hl_re_nodes:
            if node.kind == "book_header" and node.user_book_id == user_book_id:
                if node.resolved_uid is None:
                    raise ValueError(f"Book action for {user_book_id} was not resolved")
                return node.resolved_uid

        raise ValueError(f"No book UID found for {user_book_id}")

    def _get_or_create_child(
        self,
        child_blocks: list[dict[str, Any]],
        parent_uid: str | int,
        content: str,
        kind: ActionKind,
        user_book_id: int | None = None,
    ) -> tuple[str | int, list[dict[str, Any]]]:
        for block in child_blocks:
            if block.get("text") == content:
                return block["uid"], block.get("children", [])

        child_node = self.node_builder.instantiate_node(
            kind,
            parent_uid,
            content,
            None,
            user_book_id,
        )
        self.target_re_nodes.append(child_node)
        return child_node.uid, []


class DNExportWriteback:
    """
    Persist the local SQLite record of a completed daily note export.
    """

    def __init__(self, roam_client: RoamClient) -> None:
        self._session: Session = get_session(fetch_user_config().db_path)
        self._roam_client = roam_client
        self._export_batch: RoamExportBatch | None = None

    def persist_many(
        self,
        hl_node_lists: list[list[RoamExportNode]],
    ) -> None:
        self._export_batch = RoamExportBatch(database_write_time=datetime.now())
        self._session.add(self._export_batch)
        for hl_nodes in hl_node_lists:
            self._persist_hl_nodes(hl_nodes)
        self._session.commit()
        self._session.close()

    def _persist_hl_nodes(
        self,
        hl_nodes: list[RoamExportNode],
    ) -> None:
        page = self._upsert_roam_page(hl_nodes)
        self._insert_roam_book_exports_and_roam_highlight_exports(hl_nodes)
        self._insert_roam_highlight_snapshots(hl_nodes)
        self._create_page_snapshot(
            page_uid=page.page_uid,
            header_uid=page.highlights_header_uid,
            page=page,
        )

    def _upsert_roam_page(
        self,
        hl_nodes: list[RoamExportNode],
    ) -> RoamPage:
        page_uid = hl_nodes[0].page_uid
        existing_page = self._session.get(RoamPage, page_uid)
        new_rwh_node = None
        for hl_node in hl_nodes:
            if hl_node.kind == "readwise_header":
                new_rwh_node = hl_node
                break

        if existing_page:
            if new_rwh_node is None:
                return existing_page

            rwh_uid_unchanged = (
                existing_page.highlights_header_uid == new_rwh_node.resolved_uid
            )
            rwh_text_unchanged = (
                existing_page.highlights_header_text
                == new_rwh_node.body["block"]["string"]
            )

            if rwh_uid_unchanged and rwh_text_unchanged:
                return existing_page

            existing_page.highlights_header_uid = new_rwh_node.resolved_uid
            existing_page.highlights_header_text = new_rwh_node.body["block"]["string"]
            existing_page.export_batch = self._export_batch
            return existing_page

        if new_rwh_node is None:
            raise ValueError(f"No readwise header node found for {page_uid}")

        page = RoamPage(
            page_uid=page_uid,
            highlights_header_uid=new_rwh_node.resolved_uid,
            highlights_header_text=new_rwh_node.body["block"]["string"],
            export_batch=self._export_batch,
        )
        self._session.add(page)
        return page

    def _insert_roam_book_exports_and_roam_highlight_exports(
        self,
        hl_nodes: list[RoamExportNode],
    ) -> None:
        for action in hl_nodes:
            if action.kind == "book_header" and action.user_book_id is not None:
                self._session.add(
                    RoamBookExport(
                        user_book_id=action.user_book_id,
                        page_uid=action.page_uid,
                        parent_block_uid=action.resolved_uid,
                        export_date=action.export_date,
                        export_batch=self._export_batch,
                    )
                )

            elif (
                action.kind == "highlight"
                and action.highlight_id is not None
            ):
                self._session.add(
                    RoamHighlightExport(
                        highlight_id=action.highlight_id,
                        page_uid=action.page_uid,
                        block_uid=action.resolved_uid,
                        export_date=action.export_date,
                        export_batch=self._export_batch,
                    )
                )

    def _insert_roam_highlight_snapshots(
        self,
        hl_nodes: list[RoamExportNode],
    ) -> None:
        highlight_trees: list[dict[str, Any]] = []

        for hl_node in hl_nodes:
            if hl_node.kind == "highlight":
                highlight_trees.append(
                    {
                        "highlight_id": hl_node.highlight_id,
                        "uid": hl_node.resolved_uid,
                        "text": hl_node.body["block"]["string"],
                        "order": None,
                        "children": [],
                    }
                )

        for tree in highlight_trees:
            for hl_node in hl_nodes:
                if (
                    hl_node.kind == "note"
                    and hl_node.resolved_parent_uid == tree["uid"]
                ):
                    tree["children"].append(
                        {
                            "uid": hl_node.resolved_uid,
                            "text": hl_node.body["block"]["string"],
                            "order": None,
                            "children": [],
                        }
                    )

        for tree in highlight_trees:
            latest_snapshot = (
                self._session.query(RoamHighlightSnapshot)
                .filter_by(highlight_id=tree["highlight_id"])
                .order_by(RoamHighlightSnapshot.version.desc())
                .first()
            )
            snapshot_version = (
                latest_snapshot.version + 1 if latest_snapshot is not None else 1
            )
            self._session.add(
                RoamHighlightSnapshot(
                    highlight_id=tree["highlight_id"],
                    block_tree=tree,
                    block_tree_hash=self.stable_hash(tree),
                    version=snapshot_version,
                    created_at=datetime.now(),
                    export_batch=self._export_batch,
                )
            )

    def _create_page_snapshot(
        self,
        page_uid: str,
        header_uid: str,
        page: RoamPage,
    ) -> None:
        block_tree = self._roam_client.fetch_block_subtree(header_uid)
        self._session.add(
            RoamPageSnapshot(
                page_uid=page_uid,
                block_tree=block_tree,
                block_tree_hash=self.stable_hash(block_tree),
                version=len(page.snapshots) + 1,
                version_date=datetime.now(),
                export_batch=self._export_batch,
            )
        )

    @staticmethod
    def stable_hash(obj: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(obj, sort_keys=True).encode("utf-8")
        ).hexdigest()


def write_batch_to_daily_notes(batch_id: int) -> None:
    db_data = DbData(batch_id)
    grouped_highlights = db_data.build()
    rc = RoamClient()
    session: Session = get_session(fetch_user_config().db_path)
    hl_node_lists: list[list[RoamExportNode]] = []

    logger.info("Exporting batch %s to Roam daily notes", batch_id)
    for target_date, books in grouped_highlights.items():
        logger.info("To daily note: %s", target_date.isoformat())
        dn_export = DNExporter(target_date, books, rc, session)
        hl_nodes, link_nodes = dn_export.export()
        hl_node_lists.append(hl_nodes)
    
        # Link nodes not currently persisted to sqlite.
        _ = link_nodes

    session.close()
    writeback = DNExportWriteback(rc)
    writeback.persist_many(hl_node_lists)
