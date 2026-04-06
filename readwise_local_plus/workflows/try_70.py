from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from tldextract import extract

from readwise_local_plus.config import fetch_user_config
from readwise_local_plus.db_operations import get_session
from readwise_local_plus.integrations.roam import RoamClient, TempUidGenerator
from readwise_local_plus.models import Book, Highlight, RoamKnownPage


logger = logging.getLogger(__name__)

READWISE_HEADER = "[[Readwise highlights]]"
READWISE_LINKS = "__Readwise Links__"


def strip_markdown_links(s: str) -> str:
    return re.sub(r'(?<!\!)\[([^\]]+)\]\([^)]+\)', r'\1', s)


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
    def roam_book_header(self):
        """
        Parent block for the book on a Roam daily note page.
        """
        clean_title = self.readable_title.strip().replace("\n", "")

        # Re-title tweet threads (if author)
        if self.category == "tweets":
            if not clean_title.lower().startswith("tweets from") and self.author:
                # Check it's a twitter handle
                if self.author.startswith("@"):
                    author = self.author.split(" ")[0][1:] if self.author else "unknown"
                else:
                    author = self.author.title()
                clean_title = f"Tweet Thread From {author}"
        
        return clean_title

    @property
    def roam_sub_header(self):
        """
        Child block of `roam_book_header`. 

        Avoids very long book headers.
        """
        sub_header = "#[[rw]]"

        if self.category == "tweets":
            sub_header += " #[[tweets]]"
        
        elif self.category == "articles":
            sub_header += " #[[articles]]"
            
            # For articles, include author as linked ref
            author = self.author.title() if self.author else None
            if author:
                sub_header += f" #[[{author}]]"

            # For articles, include domain of source url e.g. thetimes
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
    def roam_links(self):
        """
        Seperate links from book headers for brevity.

        In Roam block 'edit' mode these are extremely unweidly. 
        """
        rw_link = self.readwise_url
        rw_reader_link = self.unique_url if self.unique_url else None
        
        links = f"[rw]({rw_link})"

        # For articles source is the book source
        if self.category == "articles":
            links += f" [source]({self.source_url})"
        
        # For tweets, source is the source of the first tweet (thread or invidual tweet(s))
        if self.category == "tweets":
            links += f" [source]({self.highlights[0].url})"

        if rw_reader_link:
            links += f" [rwr]({rw_reader_link})"
        
        return links

    def __repr__(self):
        return f'DNHBook(Title="{self.readable_title}")'


class DNExportError(Exception):
    pass


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
        # logger.info(f"Create payload for batch: {self.batch_id}")
        print(f"Create payload for batch: {self.batch_id}")

        rows = self._fetch()

        for row in rows:
            self._process_row(row)

        self._session.close()

        return {
            d: list(books.values())
            for d, books in self.grouped.items()
        }

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
                    Book.source_url,
                )
            )
            .order_by(Highlight.created_at, Highlight.book_id, Highlight.id)
        )

        rows = self._session.execute(stmt).scalars().all()
        logger.info(f"{len(rows)} highlights fetched")
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

        book = self.grouped[date_key][book_id]

        book.highlights.append(
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


def batch_body():
        return {"action": "batch-actions", "actions": []}


@dataclass
class CurrentDNState:
    hl_body: dict = field(default_factory=batch_body)
    link_body: dict = field(default_factory=batch_body)
    active_body: dict = field(init=False)
    rwh_state: str = "new"
    book_state: str = "new"
    links_state: str = "new"

    def __post_init__(self):
        self.active_body = self.hl_body


class DNExporter:
    """
    Export grouped highlights to daily notes.

    Notes
    -----
    There are two non-intuitive parts to this implimentation.
    
    - `active_body` : dict 
        is switched between `hl_body` and `link_body`. These are batch 
        action bodies that are written to Roam seperarely so link body can work with
        resolved uids. `active_body` lives on the object to allow for simplicity in
        batch action creation logic i.e. all methods just operate on 'active_body'.

    - `rwh_state`, `book_state` etc : str
        are switched between "new" or "exists". They are passed to `_decide` which uses
        switch status to call either check if a uid already exists (`ensure`) which is
        expensive, or just create a new temp uid via a new batch action (`create`). 
        NOTE: `ensure` also calls `create` directly if a uid doesn't exist.
        The state values are set to "new" and changed to "exist" in `ensure_block_uid` 
        i.e. immediately when we find the block already exists.

    Therefore these values change depending on progress through an export loop: therefore
    use with caution!
    """

    def __init__(self, grouped_highlights: dict[date, list[DNBook]]):
        self.grouped_highlights = grouped_highlights
        self.uid_gen = TempUidGenerator()
        self.rc = RoamClient()
        self.state = CurrentDNState()

    def export(self):
        print("Exporting...")
        for date_as_date, list_bks in self.grouped_highlights.items():
            print(f"To daily note: {date_as_date.isoformat()} ")

            self.state = CurrentDNState()

            dn_uid = self._ensure_daily_note(date_as_date)
            rw_header_uid = self._ensure_block_uid(dn_uid, READWISE_HEADER, 1)

            for book in list_bks:
                print(f"Book:  {book.readable_title[:40]:40} Total Highlights: {len(list_bks)}")
                bh_uid = self._decide(self.state.rwh_state, rw_header_uid, book.roam_book_header, 3) 
                b_summary_uid = self._decide(self.state.book_state, bh_uid, book.roam_sub_header)

                # `roam_links` need resolved UIDs to embed under block ref'd book header
                # Add temp uids to book objs here, then reconcile
                book.book_header_uid = bh_uid

                for hl in book.highlights:
                        hl_uid = self._create_action(b_summary_uid, hl.roam_highlight)
                        if hl.roam_note:
                            self._create_action(hl_uid, hl.roam_note)

            response_json = self.rc._write(self.state.hl_body)

            self.state.active_body = self.state.link_body

            rw_links_uid = self._ensure_block_uid(dn_uid, READWISE_LINKS, 1)
            temp_ids_to_uids = response_json['tempids-to-uids']

            for book in list_bks:
                if self.state.links_state == "new":
                    book.book_header_uid = temp_ids_to_uids[str(book.book_header_uid)]
                book_link_header = f"(({book.book_header_uid}))"
                header_uid = self._decide(self.state.links_state, rw_links_uid, book_link_header)
                # Technically links could already exist but I don't care
                self._create_action(header_uid, book.roam_links)
            
            response_json = self.rc._write(self.state.link_body)

    def _ensure_daily_note(self, target_date: date):
        session = get_session(fetch_user_config().db_path) 
        dn_uid = self.rc.date_to_roam_daily_note(target_date)
        
        if not session.get(RoamKnownPage, dn_uid):
            dn_long = self.rc._format_daily_note_title_long_format(target_date)
            try:
                self.rc.create_page(dn_long, exists_ok=True)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Failed to ensure daily note %s exists: %s", dn_uid, exc)
            session.add(RoamKnownPage(page_uid=dn_uid, last_verified_at=datetime.now()))
            session.commit()
        
        session.close()
        
        return dn_uid

    def _decide(self, relevant_state: str, *args):
        """
        Decide between calling `ensure` or `create` based on if parent uid exists.

        i.e. if the RW header doesn't exist, the book can't exist. We want to call
        `create` immediately as `ensure` is expensive.
        """
        if relevant_state == "new":
            temp_uid = self._create_action(*args)

        elif relevant_state == "exists":    
            temp_uid = self._ensure_block_uid(*args)
        else:
            raise DNExportError("uid switch status not recognised")
        
        return temp_uid

    def _set_state(self, content):
        if content == READWISE_HEADER:
            self.state.rwh_state = "exists"
        elif content == READWISE_LINKS:
            self.state.links_state = "exists"
        else:
            self.state.book_state = "exists"

    def _ensure_block_uid(
        self, parent_uid: str, content: str, heading: int|None = None
        ) -> str | None:
        child_blocks = self.rc.fetch_child_blocks(parent_uid)
        if child_blocks:
            for block in child_blocks:
                block_content = list(block.keys())[0]
                if block_content == content:
                    self._set_state(content)
                    return list(block.values())[0]
        
        temp_uid = self._create_action(parent_uid, content, heading)
        return temp_uid

    def _create_action(
            self, parent_uid: str, content: str, heading: int|None = None
        ) -> dict:
        temp_uid = self.uid_gen.next()
        location = {"order": "last", "parent-uid": parent_uid}
        block = {"string": content, "uid": temp_uid}
        
        if heading:
            block['heading'] = heading
        
        self.state.active_body["actions"].append(
            {"action": "create-block", "location": location, "block": block}
        )
        return temp_uid


def main():
    dnhp = DNHighlightsPayload(60)
    grouped_highlights = dnhp.build()
    dne = DNExporter(grouped_highlights)
    dne.export()


if __name__ == "__main__":
    main()
    


