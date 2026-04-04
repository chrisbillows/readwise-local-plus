import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
import re

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

from readwise_local_plus.workflows.tree import Node

logger = logging.getLogger(__name__)


def strip_markdown_links(s: str) -> str:
    """
    Remove markdown links from a string of text.

    Uses a look behind to avoid altering images.
    """
    return re.sub(r'(?<!\!)\[([^\]]+)\]\([^)]+\)', r'\1', s)

@dataclass
class DNHighlight:
    """
    Fields required to export a highlight to a Roam Daily Note.
    """
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
        hl = self.text.strip().replace("\n", "")
        return strip_markdown_links(hl)

    @property
    def roam_note(self) -> str:
        return self.note.strip().replace("\n", "") 

    def __repr__(self):
        text = self.text[:80].strip().replace("\n", "")
        if len(text) == 80:
            text += "..."
        return f'DNHiglight(Text="{text}")'
    
@dataclass
class DNBook:
    """
    Fields required to export a book to a Roam Daily Note.
    
    Note: `first_highlight` is taken for access to highlight level
    data e.g. `url` for use in book level links.
    """
    user_book_id: int
    title: str
    author: str
    readable_title: str
    source: str
    unique_url: str
    category: str
    readwise_url: str
    source_url: str
    first_highlight: DNHighlight

    @property
    def roam_book_header(self):
        """
        Parent block for the book on a Roam daily note page.
        """
        clean_title = self.readable_title.strip().replace("\n", "")

        # Re-title tweet threads
        if self.category == "tweets":
            if not clean_title.lower().startswith("tweets from"):
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
            links += f" [source]({self.first_highlight.url})"

        if rw_reader_link:
            links += f" [rwr]({rw_reader_link})"
        
        return links

    def __repr__(self):
        return f'DNHBook(Title="{self.readable_title}")'


class DNHighlightsPayload:
    """
    Build plain-Python daily note payloads from ORM highlights.
    """
    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        self._session: Session = get_session(fetch_user_config().db_path)
        self.raw_highlights: list[Highlight] = []
        self.dn_highlights: list[DNHighlight] = []
        self.dn_books: dict[int, DNBook] = {}
        self.grouped_highlights: defaultdict[list] = defaultdict(lambda: defaultdict(list))

    def build(self) -> tuple[defaultdict[date, dict[int, DNHighlight]], list[DNBook]]:
        """
        Build intermediate objects for creating a daily note export tree.

        Book objects are created outside of the grouped output. This keeps later 
        formatting steps as flexible as possible.

        Returns
        -------
        tuple[defaultdict[date, dict[int, DNHighlight]], list[DNBook]
            A tuple containing:
                - a default dict of DNHighlights grouped by date and by book 
                - a list of unique DNBooks in the batch
        """
        logger.info(f"Create Roam Daily Note Payload for batch: {batch_id}")
        self._fetch_raw_highlights()
        self._convert_highlights()
        self._group_highlights()
        self._session.close()
        return (self.grouped_highlights, self.dn_books)

    def _fetch_raw_highlights(self):
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
            .order_by(Highlight.book_id, Highlight.id)
        )

        self.raw_highlights = self._session.execute(stmt).scalars().all()
        logger.info(f"{len(self.raw_highlights)} highlights in batch {self.batch_id}")

    def _convert_highlights(self):
        """
        Convert raw highlights into DNHighlight and DNBook objects.
        """
        unique_user_book_ids = set()

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
            )
            self.dn_highlights.append(dn_highlight)

            if highlight.book.user_book_id not in unique_user_book_ids:
                
                unique_book = DNBook(
                    user_book_id=highlight.book.user_book_id,
                    title=highlight.book.title,
                    author=highlight.book.author,
                    readable_title=highlight.book.readable_title,
                    source=highlight.book.source,
                    category=highlight.book.category,
                    unique_url=highlight.book.unique_url,
                    readwise_url=highlight.book.readwise_url,
                    source_url=highlight.book.source_url,
                    first_highlight=dn_highlight,
                )
                unique_user_book_ids.add(highlight.book.user_book_id)
                self.dn_books[highlight.book.user_book_id] = unique_book

    def _group_highlights(self):
        """
        Group highlights by daily note date and by book id.
        """
        for dn_highlight in self.dn_highlights:
            daily_note_date = dn_highlight.created_at.date()
            book = dn_highlight.user_book_id
            self.grouped_highlights[daily_note_date][book].append(dn_highlight)


def ensure_payload_daily_notes_exist(
        grouped_highlights: defaultdict[date, dict[int, DNHighlight]]
    ):
    """
    Ensure the daily note for the payload's target date exists in Roam, creating it if necessary.

    Daily notes are stored in the RoamKnownPage table.
    """
    roam_client = RoamClient()
    session = get_session(fetch_user_config().db_path) 
    
    for target_date in grouped_highlights.keys():
        daily_note_uid = roam_client.date_to_roam_daily_note(target_date)
        existing_page = session.get(RoamKnownPage, daily_note_uid)
        if (
            existing_page is None
            and session.get(RoamKnownPage, daily_note_uid) is None
        ):
            daily_note_long_format = (
                roam_client._format_daily_note_title_long_format(target_date)
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
        session.close()


def create_roam_export_trees(
        grouped_highlights: defaultdict[date, dict[int, DNHighlight]], 
        unique_books: dict[int, DNBook]
    ) -> list[Node]:
    """
    Create a list of trees of nested Nodes for each date.

    Returns
    -------
    daily_note_nodes

    """
    daily_note_trees = []
    
    for daily_note_date, book_dict in grouped_highlights.items():
        daily_note_node = Node("daily_note", daily_note_date)
        
        for user_book_id, highlights in book_dict.items():
            dn_book = unique_books[user_book_id]

            book_header_node = Node("book_header", dn_book.roam_book_header)
            daily_note_node.add_child(book_header_node)

            book_summary_node = Node("book_summary", dn_book.roam_sub_header)
            book_header_node.add_child(book_summary_node)

            for highlight in highlights:
                highlight: DNHighlight

                highlight_node = Node("highlight_text", highlight.roam_highlight)
                book_summary_node.add_child(highlight_node)
                
                if highlight.roam_note:
                    note_node = Node("highlight_note", highlight.roam_note)
                    highlight_node.add_child(note_node)
        
        daily_note_trees.append(daily_note_node)

    return daily_note_trees

def main(batch_id: int):
    dnhp = DNHighlightsPayload(batch_id)
    grouped_highlights, unique_books = dnhp.build()
    # ensure_payload_daily_notes_exist(grouped_highlights)
    trees = create_roam_export_trees(grouped_highlights, unique_books)
    
    def foo(node: Node):
        print(f"{node.type}: {node.data}")
        for node_obj in node.children:
            foo(node_obj)

    for node in trees:
        print("-----------------------")
        foo(node)
   

if __name__ == "__main__":
    batch_id = 60  
    main(61)
    # rc = RoamClient()
    # x = rc.fetch_block_subtree("pQq5WDtmJ")
    # x = rc.write_child_block("04-03-2026", f"Does this say hello? ((y-hLxZCNr))")
    # print(x)

