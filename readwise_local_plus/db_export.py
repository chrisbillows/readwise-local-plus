"""
Classes and helpers for working with db data for read-online processing.

These classes should replicate (and expand) the SQL Alchemy ORM objects 
for "read-only" use i.e. where nothing ever needs writing back to the
database.

The primary classes `BookFromDb` and `HighlightFromDb` are exhaustive: they
include all data from the `Book` and `Highlight` ORM models, as well as 
additional fields required (or useful) for any workflow. Create workflow
specific objects if performance is an issue.
"""
from __future__ import annotations


from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, date
import logging
from pathlib import Path
import re
from typing import Any, TypeVar
from urllib.parse import urlparse

from sqlalchemy import Select, select
from sqlalchemy.orm import contains_eager

from readwise_local_plus.models import Base
from readwise_local_plus.config import UserConfig, fetch_user_config
from readwise_local_plus.db_operations import get_session
from readwise_local_plus.models import Book, Highlight


logger = logging.getLogger(__name__)

T = TypeVar("T")


def dataclass_from_orm(cls: type[T], orm_object: Base, **overrides: Any) -> T:
    """
    Instantiate a given class or dataclass from an orm object.

    Parameters
    ----------
    cls : T
        The class or dataclass to instantiate.
    orm_object : Base
        The orm object to extract values from e.g. `Book`, `Highlight` etc.
    **overrides: Any
        Additional attributes to pass to the class instantiator.
    Returns
    -------
        An instantiated object of the given `cls` type.
    """
    values = orm_object.dump_column_data()
    values.update(overrides)

    if is_dataclass(cls):
        init_fields = {
            field.name for field in fields(cls) if field.init
        }
        kwargs = {
            name: values[name]
            for name in init_fields if name in values
        }
    else:
        kwargs = values

    return cls(**kwargs)


class DbHls:
    # Key is shortname : string, value is a db query : Select[tuple[Highlight]]
    DB_QUERIES = {
        "snipd" : (
            select(Highlight)
            .join(Highlight.book)
            .join(Highlight.batch)
            .where(
                Book.category == "podcasts",
                Book.source == "snipd",
            )
            .options(
                contains_eager(Highlight.book),
                contains_eager(Highlight.batch),
            )
            .order_by(
                Highlight.book_id,
                Highlight.highlighted_at,
                Highlight.id,
            )
        ),
    }

    def __init__(self, query_shortname: str, batch_id: int | None = None):
        """
        Enrichd Hls in mutliple groupings from a shortname db query.

        Primary generalised export object. Runs the given db query
        (via shortname), groups Hls into multiple export friendly shapes
        and enriches Hls into export ready formats (via `BaseFmtr`
        objects).

        Allows creation of export specific data shapes but keeps those
        shapes sharable and reusable across export targets.

        Define db queries/shortnames `db_export.DB_QUERIES`.

        NOTE: The data collections are not intended for direct mutation
        although this isn't prevented. Rerunning `_populate` may produce
        correct update downstream data states - but this is not guaranteed.

        Beyond the below, various attrs are gated as private for simplicity.
        These are intemediate data states less likely to be useful, but are
        useable.

        Parameters
        ----------
        query_shortname : str
            Lookup for the required db query in `db_export.DB_QUERIES`
        batch_id : int | None, default = `None`
            A batch id, if present, used to construct the `db_query`.
        Attributes
        ----------
        db_query : Select[tuple[Highlight]]
            The database query as a SQLAlchemy `Select` statement.
        user_config : UserConfig
            A rwlp user config object.
        db_path : Path
            The rwlp sqlite db path from the user_config.

        Properties
        ----------
        hls_by_book : list[BookFromDb]
            Hls grouped by book as a list.
        hls_by_snipd_url : list[SnipdEpisodeFromDb]
            Hls grouped into unique episodes by snipd URL as a list.
        """
        self.query_shortname: str = query_shortname
        self.batch_id: int| None = batch_id 
        self.db_query: Select[tuple[Highlight]] = self.DB_QUERIES[query_shortname]
        self.user_config: UserConfig = fetch_user_config()
        self.db_path: Path = self.user_config.db_path
        self._hls_by_book_dict: dict[int, BookFromDb] = {}
        self._hls_by_book: list[BookFromDb] | None = None
        self._hls_by_snipd_url_dict: dict[str, SnipdEpisodeFromDb] | None = None
        self._hls_by_snipd_url: list[SnipdEpisodeFromDb] | None = None
        self._populate()

    @property
    def hls_by_book(self) -> list[BookFromDb]:
        """
        Hls grouped by book as a list.

        NOTE: Books are not reliably deduplicated by Readwise in edge cases.
        It may be preferable to add a deduplication step on export. See
        `hls_by_snipd_url` and the resultant workflow as an example.

        Returns
        -------
        list[BookFromDb]
            A list of BookFromDbs, including Hls enriched by any configured
            `BaseFmtr`.
        """
        # Build once, lazy cache
        if not self._hls_by_book:
            self._hls_by_book = list(self._hls_by_book_dict.values())
        return self._hls_by_book

    @property
    def hls_by_snipd_url(self) -> list[SnipdEpisodeFromDb]:
        """
        Hls grouped into unique episodes by snipd URL as a list.

        Readwise does not reliabily deduplicate snipd episodes. Snipd URL is the
        reliable provider of uniqueness.

        Returns
        -------
        list[SnipdEpisodeFromDb]
            A list of SnipdEpisodeFromDbs, including HLs enriched by any
            configured `BaseFmtr`.
        """
        # Build once, lazy cache
        if not self._hls_by_snipd_url:
            if not self._hls_by_snipd_url_dict:
                self._generate_hls_by_snipd_url_dict()
            self._hls_by_snipd_url = list(self._hls_by_snipd_url_dict.values())
        return self._hls_by_snipd_url

    def _populate(self):
        """
        Populate the object.

        Run before accessing properties on Hl state not guaranteed.

        """
        self._fetch_db_query()
        self._fetch_query_and_group_hls_by_book_id_and_book()
        self._enrich_highlights()

    def _fetch_db_query(self):
        """
        Populate the db_query from the `query_shortname` and optional `batch_id`

        Raises
        ------
        KeyError
            If `query_shortname` not in `DB_QUERIES`.
        """
        # Currently odd loop, live with it bro!
        try:
            query = self.DB_QUERIES[self.query_shortname]
        except KeyError as err:
            logger.error(
                "The `query_shortname`", 
                self.query_shortname, 
                "not found in `DB_QUERIES`."
            )
            raise err

        if not self.batch_id == "all":
            query = query.where(Highlight.batch_id == self.batch_id)

        self.db_query = query

    def _fetch_query_and_group_hls_by_book_id_and_book(self):
        """
        Initial db fetch for the object's query.

        Creates a dictionary where the key is a book id and the value is
        a BookFromDB with highlights as an attribute. This is a de facto
        "standard" export format which can be readily reformatted without
        requiring a SQL Alchemy session. 
        """
        with get_session(self.db_path) as session:
            for highlight in session.scalars(self.db_query):
                book_id = highlight.book_id
                book = self._hls_by_book_dict.get(book_id)

                if book is None:
                    snipd_uid = self._get_snipd_uid(highlight.book.source_url)
                    book = dataclass_from_orm(
                        BookFromDb,
                        highlight.book,
                        import_date=highlight.book.batch.database_write_time,
                        snipd_uid=snipd_uid,
                        snipd_url=highlight.book.source_url
                    )
                    self._hls_by_book_dict[book_id] = book

                book.highlights.append(
                    dataclass_from_orm(
                        HighlightFromDb,
                        highlight,
                        import_date=highlight.batch.database_write_time,
                        book_source=book.source,
                        book_snipd_url=book.source_url,
                        book_snipd_uid=book.snipd_uid,
                    )
                )

    def _enrich_highlights(self) -> None:
        """
        Add all attributes to all Hls.

        This includes all fmtd attributes for the hl type. E.g. adds
        derived attrs via the HighlightFromDb itself and/or with a
        `BaseFmtr`, if configured.
        """
        for book in self._hls_by_book_dict.values():
            for hl in book.highlights:
                hl._populate()
                fmtr_ins: BaseFmtr = self._get_hl_processor(hl)
                if fmtr_ins:
                    fmtr_ins.populate_hl()

    def _generate_hls_by_snipd_url_dict(self) -> dict[str, SnipdEpisodeFromDb]:
        """
        Hls grouped into unique episodes by snipd URL as a dictionary.

        Readwise does not reliabily deduplicate snipd episodes. Snipd URL is the
        reliable provider of uniqueness.

        Create from `self.hls_by_book_dict` rather thanb from the DB to allow access
        to book metadata.

        NOTE: Mutating the DB output is not intended behaviour. If doing so, manually
        delete `self.hls_by_book_dict` to force recalculation.

        Returns
        -------
        dict[str, SnipdEpisodeFromDb]
            A dict where the key is a Snipd URL and the values are SnipdEpisodeFromDbs
            sorted by , with highlights sorted by `highlighted_at`.
        """
        # Build once, lazy cache
        if self._hls_by_snipd_url_dict is None:
            cache: dict[str, SnipdEpisodeFromDb] = {}

            for book in self._hls_by_book_dict.values():
                snipd_uid = self._get_snipd_uid(book.source_url)

                if snipd_uid in cache:
                    cache[snipd_uid].books.append(book)

                else:
                    book.highlights.sort(key=lambda hl: hl.highlighted_at)
                    snipd_episode = SnipdEpisodeFromDb(
                        snipd_url=book.source_url,
                        snipd_uid=snipd_uid,
                        books=[book]
                    )
                    cache[snipd_uid] = snipd_episode

            self._hls_by_snipd_url_dict = cache

    @staticmethod
    def _get_hl_processor(hl: HighlightFromDb) -> T:
            """
            Generate a processor for the Hl for a given workflow.

            If the Hl is not exported as part of the workflow, set to `None`.     
            """
            if hl.snipd_hl_type == "transcript":
                fmtr_ins = SnipdTranscriptFmtr(hl)
            elif hl.snipd_hl_type == "episode-ai-notes":
                fmtr_ins = SnipdAiEpisodeNotesFmtr(hl)
            else:
                fmtr_ins = None

            return fmtr_ins

    def _sort_and_filter_highlights_for_snipd(hl: HighlightFromDb) -> HighlightFromDb:
        """
        TODO: This will create the final sorted, filtered list of highlights...
        So probably on each episode???
        """
        pass

    @staticmethod
    def _get_snipd_uid(url: str) -> str:
        """
        Extract snipd uif from a snipd URL.

        Parameters
        ----------
        snipd_url : str
            A snipd_url for a podcast episode or an individual snip.

        Returns
        -------
        str
            The extracted snipd uid.
        """
        return urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]


class FmtdHl:
    """
    Data collection class for HighlightFromDb to attach formatter-generated state.

    Wild west grouping of any and all intermediate and final states.

    Intermediate states will be classed as private e.g. '_<attr>'
    """

    def __repr__(self):
        return f"HlFmtd({', '.join(vars(self).keys())})"


class HighlightFromDb:
    """
    Representing a Hl exported from the rw db.

    Includes all ORM model fields, as well as additional useful fields. Designed
    for ease of development rather than effeciency. Workflow specific fields
    are generated here to faciliate reusability across workflows.

    NOTE: For Snipd, both Episodes (i.e. Books) and Hls have their own URLs
    and UIDs. Both are available on the object. The Hl URL is `self.url` 
    and the episode/book url is `self.book_snipd_url`. Examples:

    - `https://share.snipd.com/episode/<uid>`
    - `https://share.snipd.com/snip/<uid>`
    

    Parameters (notable only - most duplicate ORM model Highlight)
    --------------------------------------------------------------
    book_snipd_url : str
        Technically the Book's `source_url` added for developer ergonomics. 
    """
    def __init__(
        self,
        id: int,
        book_id: int,
        batch_id: int,
        text: str,
        location: int | None,
        location_type: str | None, 
        note: str | None,
        color: str | None,
        highlighted_at: datetime | None,
        created_at: datetime | None,
        updated_at: datetime | None,
        external_id: str | None,
        end_location: int | None,
        url: str | None,
        is_favorite: bool | None,
        is_discard: bool | None,
        is_deleted: bool | None,
        readwise_url: str | None,
        validated: bool,
        validation_errors: dict[str, str],
        book_source: str | None,
        import_date: datetime,
        book_snipd_url: str | None,
        book_snipd_uid: str | None,
        ):
        # Table fields
        self.id: int = id
        self.book_id: int = book_id
        self.batch_id: int = batch_id
        self.text: str = text
        self.location: int | None = location
        self.location_type: str | None = location_type
        self.note: str | None = note
        self.color: str | None = color
        self.highlighted_at: datetime | None = highlighted_at
        self.created_at: datetime | None = created_at
        self.updated_at: datetime | None = updated_at
        self.external_id: str | None = external_id
        self.end_location: int | None = end_location
        self.url: str | None = url
        self.is_favorite: bool | None = is_favorite
        self.is_discard: bool | None = is_discard
        self.is_deleted: bool | None = is_deleted
        self.readwise_url: str | None = readwise_url
        self.validated: bool = validated
        self.validation_errors: dict[str, str] = validation_errors
        # Additional fields
        self.book_source: str | None = book_source
        self.import_date: datetime = import_date 
        self.book_snipd_url: str | None = book_snipd_url
        self.book_snipd_uid: str | None = book_snipd_uid
        self.hl_type: str | None = None
        self.snipd_hl_type: str| None = None
        self.fmtd: FmtdHl | None = None

    def _populate(self) -> None:
        """
        Driver function to populate all calculated obj fields.
        """
        self._generatre_hl_type()
        self._generate_snipd_hl_type()

    def _generatre_hl_type(self) -> None:
        """
        Rwlp internal Hl type.

        Used for processing.

        Independent from `book_source` to allow for more complex definitions.
        """
        if self.book_source == "snipd":
            self.hl_type = "snipd"

    def _generate_snipd_hl_type(self) -> None:
        """
        Snipd Hl type.

        Used for processing.

        Types are `'transcript'`, `'episode-ai-notes'`. `'do-not-process'`
        indicates oddities we do not process.
        """
        if self.hl_type != "snipd":
            type = None
        
        elif "Transcript:" in self.text and "Episode AI notes" in self.text:
            warning_msg = (
                "Highlight id: " +
                str(self.id) +
                " in book id: " +
                str(self.user_book_id) +
                " has 'Transcript:' and 'Episode AI notes' strs. Did not process."
                )
            logger.warning(warning_msg)
            type = "do-not-process"
            
        elif "Transcript:" in self.text:
            type = "transcript"
    
        elif "Episode AI notes" in self.text:
            type = "episode-ai-notes"
    
        else:
            type = "do-not-process"

        self.snipd_hl_type = type   

    def __repr__(self) -> str:
        return f"HL(id:{self.id})"


@dataclass
class BookFromDb:
    # DB fields
    user_book_id: int
    batch_id: int
    title: str
    is_deleted: bool | None
    author: str
    readable_title: str | None
    source: str | None
    cover_image_url: str | None
    unique_url: str | None
    summary: str | None
    category: str | None
    document_note: str | None
    readwise_url: str | None
    source_url: str | None
    external_id: str | None
    asin: str | None
    validated: bool
    validation_errors: dict[str, str]
    # Additional fields
    import_date: datetime
    snipd_url: str | None  # Duplicate of `source_url` for developer ease
    snipd_uid: str | None
    highlights: list[HighlightFromDb] = field(default_factory=list)

    @property
    def created_at(self) -> datetime:
        """
        Return the earliest highlight `created_at` value.
        """
        created_dates = [hl.createdq_at for hl in self.highlights]
        created_dates.sort()
        return created_dates[0]

    def __repr__(self) -> str:
        total_highlights = len(self.highlights)
        return f"Book(HLs: {total_highlights} | {self.title})"


class SnipdEpisodeFromDb:
    """
    Grouping of Books from the same snipd episode.

    Snipd episodes are unique based on snipd url (or the derived snipd uid). Class 
    groups those books together. For ease of development, instantiated as a list of
    books to allow access to any required book metadata.
    """

    OBS_ILLEGAL_CHARS_TABLE = str.maketrans(dict.fromkeys('*"\\/<>:|?#^[]'))
    PODCAST_TITLE_MAP = {
        "The Rest Is History": "Rest Is History",
        "The Rest Is Politics": "Rest Is Politics",
    }

    def __init__(self, snipd_url: str, snipd_uid: str, books: list[BookFromDb]):
        """
        
        Parameters
        ----------
        snipd_url : str
            The episode's unique snipd url.
        snipd_uid : str
            The episode's unique snipd uid, extracted from the snipd url.
        books : list[BookFromDb]
            All books that share the same snipd_url (as `source_url`). Hls
            may be duplicates/versions or may not. Books are sorted oldest
            to newest.
        
        Attributes
        ----------
        full_page : str
            The final export output to Obsidian. Combines
            `page_front_matter` and `page_body`.
        fmtd_hls : list
            Obsidian fmtd lastest highlights. Used to create `page_body`.
        hls : list[HighlightFromDb]
            Latest version of all Hls; deduplicated and sorted by location/highlighted_at.
        all_hl_versions : list[HighlightFromDb]
            Every version of every highlight ever imported into Readwise.
        podcast_title : str
            Obsidian safe podcast title, updated per user spec if included in
            `PODCAST_TITLE_MAP`.
        episode_title : str
            Obsidian safe podcast episode title.
        page_front_matter : str
            The front matter block as a string with newlines.        
        page_body : str
            The fmtd Hls output by a Fmtr, incrementally added into
            a string with newlines.
        """
        self.snipd_url: str = snipd_url
        self.snipd_uid: str = snipd_uid
        self.books: list[BookFromDb] = books
        self.hls: list[HighlightFromDb] = []
        self.fmtd_hls: list[str] = []
        self.all_hl_versions: list[HighlightFromDb] = []
        self.podcast_title: str = ""
        self.episode_title: str = ""
        self.page_front_matter: str = ""
        self.page_body: str = ""
        self.full_page: str = ""

    def populate(self) -> None:
        """
        Driver method to populate the object.
        """
        self._generate_podcast_title()
        self._generate_episode_title()
        self._generate_hls()
        self._generate_front_matter()
        self._generate_page_body()
        self.full_page = self.page_front_matter + self.page_body

    def _generate_hls(self) -> list[HighlightFromDb]:
        """
        A list of hls from all books in the snipd episode, sorted by `highlighted_at`.
        """
        self.all_hl_versions = [hl for book in self.books for hl in book.highlights]

        grouped_by_snipd_url = self._group_hls_by_snipd_url(self.all_hl_versions)
        deduplicated_hls = self._deduplicate_hls(grouped_by_snipd_url)

        # NOTE: AI notes have an int 0 location. This sort puts them first.
        deduplicated_hls.sort(key=lambda hl: (hl.location, hl.highlighted_at))

        self.hls = deduplicated_hls

        # Below retained temporarily for future debugging.
        def display_hl(hl):
            uid = hl.url.replace("//", "/").split("/")[3][:12]
            print(
                f"{hl.location:5}      "
                f"{hl.highlighted_at.isoformat(timespec='minutes', sep=" ")}      "
                f"{hl.created_at.isoformat(timespec='minutes')}      {uid}"
            )

        snipd_hl_debug = False
        if snipd_hl_debug:
            print(f"===== {self.books[-1].user_book_id} | {self.books[-1].title} ======")
            print("\n-------------------------------all_hls ---------------------------")
            print("  loc   |    highlighted_at   |     created at     |    snipd_uid \n")

            for hl in self.all_hl_versions:
                display_hl(hl)

            print("\n---------------------------- sorted dedupes-----------------------")
            print("  loc   |    highlighted_at   |     created at     |    snipd_uid \n")
            for hl in deduplicated_hls:
                display_hl(hl)

            print(f"\nTotal all_hls        : {len(self.all_hl_versions)} ")
            print(f"Total deduplicate_hls: {len(deduplicated_hls)}\n")

    def _group_hls_by_snipd_url(self) -> dict[str, list[HighlightFromDb]]:
        """
        Group by snipd url (e.g. `HighlightFromDb.url`).

        Assumes snipd url indicates a unique Hl and therefore the grouped
        duplicates are versions.

        Raises
        ------
        KeyError
            If a hl has no `url`. Should be impossible.

        Returns
        -------
        dict[str, list[h]]
            Hls grouped by snip url
        """
        grouped_by_snipd_url = {}

        for hl in self.all_hl_versions:
            if not hl.url:
                raise KeyError

            if not grouped_by_snipd_url.get(hl.url):
                grouped_by_snipd_url[hl.url] = [hl]
            else:
                grouped_by_snipd_url[hl.url].append(hl)

        return grouped_by_snipd_url

    def _deduplicate_hls(
            self, grouped_by_snipd_url: dict[str, list[HighlightFromDb]]
        ):
        """
        Deduplicate a  by most recent created_at.
        """
        latest_versions = []
        for hls in grouped_by_snipd_url.values():
            latest = max(hls, key=lambda hl: hl.created_at)
            latest_versions.append(latest)

        return latest_versions

    def _generate_page_body(self) -> None:
        """
        Create the page body and group fmtd hls as a list.

        Currently handled per `snipd_hl_type` but this
        may be generalised via `BaseFmtr` at a later
        date.
        """
        for hl in self.hls:
            if hl.snipd_hl_type == 'transcript':
                self.fmtd_hls.append(hl.fmtd.hl_full)
                self.page_body += hl.fmtd.hl_full
            if hl.snipd_hl_type == 'episode-ai-notes':
                self.fmtd_hls.append(hl.hl_full)
                self.page_body += hl.hl_full

    def _obs_safe_filenames_and_frontmatter(self, s: str) -> str:
        """
        Limit length and remove banned obsidian chars from a str.
        """
        if len(s) > 100:
            s = s[:100] 
        return s.translate(self.OBS_ILLEGAL_CHARS_TABLE)
    
    def _generate_podcast_title(self) -> None:
        """
        Revise based on `PODCAST_TITLE_MAP` and ensure Obs safe.
        """
        # Books sorted oldest to newest
        book_author = self.books[-1].author
        safe_title = self._obs_safe_filenames_and_frontmatter(book_author)
        if safe_title in self.PODCAST_TITLE_MAP:
            safe_title = self.PODCAST_TITLE_MAP[safe_title]
        self.podcast_title = safe_title

    def _generate_episode_title(self) -> None:
        """
        Obs safe episode title.
        """
        # Books sorted oldest to newest
        episode_title = self.books[-1].title
        safe_episode_title = self._obs_safe_filenames_and_frontmatter(episode_title)
        self.episode_title = safe_episode_title

    def _generate_front_matter(self) -> None:
        """
        Create episode frontmatter.
        """
        front_matter_template = """---
podcast: {{podcast}}
source: {{source}}
readwise_url: {{rw_url}}
highlighted_at: {{highlighed_at}}
rw_created_at: {{rw_created_at}}
obs_import_at: {{obs_imported_at}}
total_hls: {{total_hls}}
archived_hls: {{archived_hls}}
book_id: {{book_id}}
tags:
- podcast/{{podcast_title_for_tag}}
- podcast-eps
---
"""
        title_for_tag = re.sub(r"[^A-Za-z0-9]", "", self.podcast_title)
        title_for_tag = title_for_tag.lower().replace(" ", "-")

        oldest_book = self.books[0]
        earliest_hl = min(oldest_book.highlights, key=lambda hl: hl.highlighted_at)

        most_recent_book = self.books[-1]

        total_hls = len(self.fmtd_hls)
        archived_hls = len(self.all_hl_versions) - total_hls

        template_replacements = {
            "{{podcast}}": self.podcast_title,
            "{{source}}": self.snipd_url,
            "{{rw_url}}": most_recent_book.readwise_url,
            "{{highlighed_at}}": str(earliest_hl.highlighted_at.date()),
            "{{rw_created_at}}": str(earliest_hl.created_at.date()),
            "{{obs_imported_at}}": str(date.today()),
            "{{total_hls}}": str(total_hls),
            "{{archived_hls}}": str(archived_hls),
            "{{book_id}}": str(most_recent_book.user_book_id),
            "{{podcast_title_for_tag}}": title_for_tag,
        }

        for placeholder, value in template_replacements.items():
            front_matter_template = front_matter_template.replace(placeholder, value)

        self.page_front_matter = front_matter_template + "\n"


class BaseFmtr(ABC):
    """
    Base class for Hl and Book fmtrs.
    """
    def __init__(self, hl: HighlightFromDb | BookFromDb):
        self.hl = hl

    @abstractmethod
    def populate_hl(self) -> None:
        """
        Populate the passed in hl with 'transcript' ftmd outputs.

        Populates the fmtd object on the passed in Hl.
        """


class SnipdTranscriptFmtr(BaseFmtr):

    def __init__(self, hl: HighlightFromDb):
        """
        Processor for Snipd Hl of type 'transcript'.

        Mutatates the passed in Hl by adding `FmtHl` object. The `FmtHl` 
        contains the various fmtd outputs. 

        'transcript' Hls includes the text 'Transcript:'. Transcript highlights 
        are split into: i) summary ii) quotes. The summary is then split 
        into: a) title b) body

        Each part is formatted and the result is return as `fmtd_hl`. 
        Intermediate states are preserved.

        Parameters
        ----------
        hl : HighlightFromDb
            A Snipd Hl of type 'transcript'.

        Attributes add to `Hl`
        ---------------------
        fmtd: FmtHl()
            A FtmHl object that collects the following state.
        
        Attributes added to `fmtd`
        ------------------------
        summary_title : str

        summary_body : str
            The list of strings, formatted for writing, usually as a bullets 
            seperated by newlines.
        quotes : str

        quotes_by_speaker : list[tuple[str, str]]
        
        hl_full : str
            The recombined, formatted highlight as a writeable string.
            
        """
        super().__init__(hl)
        self.hl.fmtd = FmtdHl()

        self.hl.fmtd.summary_title = ""
        self.hl.fmtd.summary_body  = ""
        self.hl.fmtd.quotes = ""
        self.hl.fmtd.hl_full = ""

        self.hl.fmtd.cleaned_text = ""

        self.hl.fmtd.summary_raw = ""
        self.hl.fmtd.quotes_raw = ""
        self.hl.fmtd.summary_title_raw = ""

        self.hl.fmtd.summary_body_type = ""
        self.hl.fmtd.summary_body_raw  = []

        self.hl.fmtd.quotes_by_speaker = [] 

    def populate_hl(self):
        """
        Populate the passed in hl with 'transcript' ftmd outputs.

        Populates the fmtd object on the passed in Hl.
        """
        self._clean_text()
        self.hl.fmtd.summary_raw, self.hl.fmtd.quotes_raw = self.hl.fmtd.cleaned_text.split("Transcript:")
    
        self.split_summary_into_title_and_body()
        self.find_summary_body_type()
    
        self._format_summary_title_raw()
        self._format_summary_body_raw()

        self._split_quotes_raw_by_speaker()
        self._format_quotes_by_speaker()
        
        self.hl.fmtd.hl_full = (
            self.hl.fmtd.summary_title + "\n\n" + self.hl.fmtd.summary_body + "\n\n" 
            + "\n".join(self.hl.fmtd.quotes) + "\n\n"
        )

    def _clean_text(self) -> None:
        """
        Initial clean of hl text.
        """
        # Remove the 'Key takeaways' str. Fmt otherwise is std bullets.
        text = self.hl.text.replace("Key takeaways:", "")
        # Make non-std bullets std.
        text = text.replace("•", "-")
        text = text.replace("*", "-")
        self.hl.fmtd.cleaned_text = text
    
    def split_summary_into_title_and_body(self) -> None:
        """
        Split a transcript highlight summary into a `title` and `body`.

        Returns
        -------
        tuple
            Where the first item is the highlight title as a string, and then 
            second item is the summary bullet points as a list of strings.
        """
        summary = self.hl.fmtd.summary_raw.replace("\n\n", "\n")
        summary_split = summary.split("\n")

        self.hl.fmtd.summary_title_raw = summary_split[0]
        self.hl.fmtd.summary_body_raw = [s for s in summary_split[1:] if s != '']
    
    def find_summary_body_type(self) -> None:
        """
        The 'type' of a transcript highlight body, for processing.

        Types are 'bullets', 'summary', 'single-block', 'multi-line',
        'no-body' and 'unknown'.
        """
        if len(self.hl.fmtd.summary_body_raw) == 0:
            body = "no-body"

        elif self.hl.fmtd.summary_body_raw[0].startswith('-'):
            body = "bullets"

        elif "Summary:" in self.hl.fmtd.summary_body_raw:
            body = "summary"

        elif len(self.hl.fmtd.summary_body_raw) == 1:
            body = "single-block"

        elif len(self.hl.fmtd.summary_body_raw) > 1:
            body = "multi-line"
        else:
            logger.warning("Hl of type 'transcript': Hl body type not known.")
            body = "unknown"

        self.hl.fmtd.summary_body_type = body

    def _format_summary_title_raw(self) -> None:
        """
        Format a string as a transcript highlight title.
        """
        # Use first bullet as title
        title = self.hl.fmtd.summary_title_raw.replace("--", "")
        title = title.replace("**", "")

        if title.startswith("-"):
            title = title[1:]

        self.hl.fmtd.summary_title = "## " + title

    def _format_summary_body_raw(self) -> str:
        """
        Convert raw summary body into to a writable string.

        Conversion depends on highlight body type.

        Returns
        -------
        str
            
        """
        match self.hl.fmtd.summary_body_type:

            case "no-body":
                body = ""

            case "bullets":
                body = "\n".join(self.hl.fmtd.summary_body_raw)

            case "summary":
                hl_body = [s for s in self.hl.fmtd.summary_body_raw if s != "Summary:"]
                bullet_body = self._make_bullets(
                    hl_body, self.hl.fmtd.summary_body_type
                    )
                body = "\n".join(bullet_body)

            case "single-block":
                split_body = self.hl.fmtd.summary_body_raw[0].split(". ")
                bullet_body = self._make_bullets(
                    split_body, self.hl.fmtd.summary_body_type
                    )
                body = "\n".join(bullet_body)

            case "multi-line":
                bullet_body = self._make_bullets(
                    self.hl.fmtd.summary_body_raw, self.hl.fmtd.summary_body_type
                    )
                body = "\n".join(bullet_body)

            case _:
                print(self.hl.fmtd.summary_body_raw)
                raise Exception

        self.hl.fmtd.summary_body = body 

    @staticmethod
    def _make_bullets(split_body: list[str], split_body_type: str) -> list[str]:
        """
        Add dashes to the start of a list of strings.
        """
        bullet_body = []
        for s in split_body:
            bullet_s = '- ' + s
            if split_body_type == "summary":
                bullet_s += "."
            bullet_body.append(bullet_s)
        return bullet_body

    def _split_quotes_raw_by_speaker(self):
        """
        Split quotes into the form `[(<speaker>, <quote>), (<speaker>, <quote>)]`.

        Quotes expected to be formatted as:

        ```
        <speaker>
        <quote>
        ```

        Assumes text was split on 'Transcript:' therefore begins with a newline. 
        """
        raw = self.hl.fmtd.quotes_raw
        raw = raw[1:]
        raw = raw.replace("\n\n", "\n")
        raw = list(raw.split("\n"))

        transcript_by_speaker = []
        for even_idx in range(0, len(raw), 2):
            speaker = raw[even_idx]
            quote = raw[even_idx + 1]
            transcript_by_speaker.append((speaker, quote))

        self.hl.fmtd.quotes_by_speaker = transcript_by_speaker

    def _format_quotes_by_speaker(self) -> None:
        """
        Format a list of split quotes.
        """
        quotes = []
        for speaker, quote in self.hl.fmtd.quotes_by_speaker:
            split_quote = self.split_on_punctuation(quote)
            fmtd_split_quote = "".join([f"> - {str}\n" for str in split_quote])
            fmtd_transcript = f"> [!quote] **{speaker}**\n{fmtd_split_quote}"
            quotes.append(fmtd_transcript)

        self.hl.fmtd.quotes = quotes

    @staticmethod
    def split_on_punctuation(quote: str) -> list:
        """
        Split text on punctuation into a list of strings.

        Handles ellipsis, fullstops, question marks and exclaimation marks.

        Parameters
        ----------
        quote: str
            A paragraph of text.

        Returns
        -------
        list
            The original text as a list of strings.
        """
        # Do first, preserve ellipsis
        quote = quote.replace("...", "...\n")
        quote = quote.replace(". ", ".\n")
        quote = quote.replace("? ", "?\n")

        split_quote = quote.split("\n")

        return split_quote


class SnipdAiEpisodeNotesFmtr(BaseFmtr):
    """
    Snipd Hl of type `Episode AI Notes`.
    """
    def __init__(self, hl: HighlightFromDb):
        super().__init__(hl)
        self.hl = hl

    def populate_hl(self):
        """
        Create the formated highlight.

        Done directly for short term speed/simplicitly.

        This function will be brittle to changes in
        Episode AI note formatting.
        """
        sentences = self.hl.text.split("\n\n")
        title = sentences[0]

        fmtd_title = f"## {title}\n"

        fmtd_sentences = []
        for sentence in sentences[1:]:

            # Sentences are numbered e.g "1. <sentence>"
            # Count chars that can be cast to digits, up to 9999
            leading_number_chars = 0
            for char in sentence[:4]:
                try:
                    int(char)
                except ValueError as err:
                    continue
                leading_number_chars += 1

            # The `+ 2` target the ". " follow the leading number chars.
            sentence_without_num = sentence[(leading_number_chars + 2):]
            sentence_by_word= sentence_without_num.replace("  ", " ").split(" ")

            # if "10." in sentence and "Gwyneth" in sentence:
            #     breakpoint()

            # Ignore fragmentary sentences, if any.
            if len(sentence_by_word) < 7:
                continue

            # Bullet and bold first five words, add ellipsis.
            # Indent remaining text under first bullet.
            sentence_by_word[0] = '- ***' + sentence_by_word[0]
            sentence_by_word[5] = sentence_by_word[5] + "..." + "***\n  -"

            fmtd_sentence =  " ".join(sentence_by_word)
            fmtd_sentences.append(fmtd_sentence)


        self.hl.hl_full = fmtd_title +"\n" + "\n\n".join(fmtd_sentences) + "\n\n"


# There is a configured `if __name__ == `__main__` for development in `obsidian_snipd.py`.
