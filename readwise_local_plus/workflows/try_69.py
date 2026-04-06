from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
import logging
from random import randint
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
READWISE_LINKS = "[[Readwise Links]]"


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
        logger.info(f"Create payload for batch: {self.batch_id}")

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


def ensure_daily_note(target_date: date, rc: RoamClient):
    session = get_session(fetch_user_config().db_path) 
    dn_uid = rc.date_to_roam_daily_note(target_date)
    if not session.get(RoamKnownPage, dn_uid):
        dn_long = rc._format_daily_note_title_long_format(target_date)
        try:
            rc.create_page(dn_long, exists_ok=True)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to ensure daily note %s exists: %s", dn_uid, exc)
        session.add(RoamKnownPage(page_uid=dn_uid, last_verified_at=datetime.now()))
        session.commit()
    session.close()
    return dn_uid


def ensure_block_uid(
        body: dict, 
        parent_uid: str, 
        content: str, 
        uid_gen: TempUidGenerator,
        rc: RoamClient,
        heading: int|None = None
    ) -> str | None:
    child_blocks = rc.fetch_child_blocks(parent_uid)
    if child_blocks:
        for block in child_blocks:
            block_content = list(block.keys())[0]
            if block_content == content:
                return list(block.values())[0]
    
    temp_uid = add_action(body, parent_uid, content, uid_gen, heading)
    return temp_uid


def add_action(
        body: dict, 
        parent_uid: str, 
        content: str, 
        uid_gen: TempUidGenerator,
        heading: int|None = None
    ) -> dict:
    temp_uid = uid_gen.next()
    location = {"order": "last", "parent-uid": parent_uid}
    block = {"string": content, "uid": temp_uid}
    
    if heading:
        block['heading'] = heading
    
    body["actions"].append(
        {"action": "create-block", "location": location, "block": block}
    )
    return temp_uid


def write_to_roam(grouped_highlights):
    uid_gen = TempUidGenerator()
    rc = RoamClient()
    hl_body = {"action": "batch-actions", "actions": []}
    link_body = {"action": "batch-actions", "actions": []}

    for date_as_date, list_bks in grouped_highlights.items():
        dn_uid = ensure_daily_note(date_as_date, rc)
        
        # Use ensure as rw header / links may already exist
        rw_header_uid = ensure_block_uid(hl_body, dn_uid, READWISE_HEADER, uid_gen, rc, 1)

        for book in list_bks:
            # Temp uids will be negative ints
            if not isinstance(rw_header_uid, int):
                # As rw header exists, use ensure as books may exist
                # Ensure is slower as requires API call
                book_header_uid = ensure_block_uid(
                    hl_body, rw_header_uid, book.roam_book_header, uid_gen, rc, 3)
                book_summary_uid = ensure_block_uid(
                    hl_body, book_header_uid, book.roam_sub_header, uid_gen, rc)
            else:
                book_header_uid = add_action(
                    hl_body, rw_header_uid, book.roam_book_header, uid_gen, 3)
                book_summary_uid = add_action(
                    hl_body, book_header_uid, book.roam_sub_header, uid_gen)

            # Links need resolved UIDs to embed under book headers
            # Add temp uids to book objs here, then reconcile
            book.book_header_uid = book_header_uid

            for hl in book.highlights:
                    hl_uid = add_action(hl_body, book_summary_uid, hl.roam_highlight, uid_gen)
                    if hl.roam_note:
                        add_action(hl_body, hl_uid, hl.roam_note, uid_gen)

        response_json = rc._write(hl_body)

        rw_links_uid = ensure_block_uid(link_body, dn_uid, READWISE_LINKS, uid_gen, rc, 1)

        tempd_ids_to_uids = response_json['tempids-to-uids']
        for book in list_bks:
            book: DNBook
            book.book_header_uid = tempd_ids_to_uids[str(book.book_header_uid)]
            book_link_header = f"(({book.book_header_uid}))"
            if not isinstance(rw_links_uid, int):
                header_uid = ensure_block_uid(
                    link_body, rw_links_uid, book_link_header, uid_gen, rc, 3
                    )
            else:
                header_uid = add_action(
                    link_body, rw_links_uid, book_link_header, uid_gen, 3
                    )
            
            book_links = add_action(link_body, header_uid, book.roam_links, uid_gen)
        response_json = rc._write(link_body)


def main():
    dnhp = DNHighlightsPayload(60)
    grouped_highlights = dnhp.build()

    # Strip out one example and overwrite group highlights
    example_date = list(grouped_highlights.keys())[0]
    example_books = grouped_highlights[example_date]
    dn = date(2026, 4, 5)
    grouped_highlights = {}
    grouped_highlights[dn] = example_books

    write_to_roam(grouped_highlights)


if __name__ == "__main__":
    main()
    


