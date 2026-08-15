"""
SQLAlchemy ORM models, associated types and validators.

The models Book, Highlight, HighlightTag and ReadwiseBatch are nested and intended to
be used in unison.

Readwise primary keys are used as database primary keys throughout for consistency with
Readwise object relationships.

Readwise API responses assume and rely upon Pydantic validation.

Note on ORM validation
----------------------
Mapped classes may seem to validate things that they actually don't:

- Type hints e.g. ``Mapped[int]`` and character limits e.g. ``String(511)`` are not
  enforced at runtime by SQLAlchemy. The underlying database dialect may - or may not -
  enforce them. SQLite is particularly permissive and enforces neither datatype nor
  character limits.

- Missing fields are accepted and default to None. This only results in an error when
  committing to the database and only if the field is ``nullable=False``.

"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    object_mapper,
    relationship,
)


class ModelDumperMixin:
    """Mixin to dump column data to a dictionary."""

    def dump_column_data(self, exclude: Optional[set[str]] = None) -> dict[str, str]:
        """
        Dump column fields and values to a dict.

        Returns
        -------
        dict[str, str]
            A dictionary where keys are column names and values are the corresponding
            values from the ORM mapped class instance.

        Parameters
        ----------
        exclude : Optional[set[str]]
            A set of column names to exclude from the output. If None, no columns are
            excluded.
        """
        exclude = exclude or set()
        return {
            column.key: getattr(self, column.key)
            for column in object_mapper(self).columns
            if column.key not in exclude
        }


class Base(DeclarativeBase, ModelDumperMixin):
    """
    Subclass SQLAlchemy ``DeclarativeBase`` base class.

    All ORM Mapped classes should inherit from ``Base``. Tables can then be created
    with ``Base.metadata.create_all``.
    """

    # This is required to avoid mypy erros. See:
    # https://docs.sqlalchemy.org/en/20/changelog/migration_20.html#migration-to-2-0-step-six-add-allow-unmapped-to-explicitly-typed-orm-models
    __allow_unmapped__ = True


class ValidationMixin:
    """
    Add validation fields to SQL Alchemy ORM mapped classes.

    Store validation errors as JSON strings. Data usage won't justify a table.

    Note
    ----
    SQLite has supported JSON types since 3.9, released in 2015-10-14. See:
    https://www.sqlite.org/changes.html

    """

    validated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validation_errors: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)


class ReadwiseLastFetch(Base):
    """
    Singleton table to store the last successful fetch time from the Readwise API.

    Used for incremental syncing with the `updatedAfter` parameter.
    """

    __tablename__ = "readwise_last_fetch"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    last_successful_fetch: Mapped[datetime] = mapped_column(nullable=False)


class BookBase(Base, ValidationMixin):
    """
    Abstract base class for Book fields (excluding relationships).
    """

    __abstract__ = True

    title: Mapped[Optional[str]]
    is_deleted: Mapped[Optional[bool]]
    author: Mapped[Optional[str]]
    readable_title: Mapped[Optional[str]]
    source: Mapped[Optional[str]]
    cover_image_url: Mapped[Optional[str]]
    unique_url: Mapped[Optional[str]]
    summary: Mapped[Optional[str]]
    category: Mapped[Optional[str]]
    document_note: Mapped[Optional[str]]
    readwise_url: Mapped[Optional[str]]
    source_url: Mapped[Optional[str]]
    external_id: Mapped[Optional[str]]
    asin: Mapped[Optional[str]]


class BookVersion(BookBase):
    """
    A version of a book with additional fields for versioning.

    This class extends the BookBase class to include versioning information.

    Attributes
    ----------
    version : int
        The version number of the book entry.
    """

    __tablename__ = "book_versions"
    batch_name = "versioned_books"

    version_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version: Mapped[int]
    versioned_at: Mapped[datetime] = mapped_column(default=datetime.now)

    batch_id_when_versioned: Mapped[int] = mapped_column(
        ForeignKey("readwise_batches.id"), nullable=False
    )
    user_book_id: Mapped[int] = mapped_column(ForeignKey("books.user_book_id"))
    batch_id_when_new: Mapped[int] = mapped_column(
        ForeignKey("readwise_batches.id"), nullable=False
    )

    batch_when_versioned: Mapped["ReadwiseBatch"] = relationship(
        back_populates="versioned_books",
        foreign_keys=[batch_id_when_versioned],
    )

    def __repr__(self) -> str:
        return (
            f"BookVersion(user_book_id={self.user_book_id!r}, "
            f"title={self.title!r}, version={self.version!r})"
        )


class Book(BookBase):
    """
    Readwise book as a SQL Alchemy ORM Mapped class.

    *WARNING* Using unvalidated API data directly with this class may result in
    unexpected behaviour and is not recommended. Validation is enforced in the Pydantic
    layer only. For example, this ORM class will accept null values for all fields -
    even those fields which should never be null. (Except the primary key which will not
    accept a null).

    Each class instance corresponds to a book dictionary from the Readwise
    'Highlight EXPORT' endpoint. "books" are parent object for all highlights, even
    those not sourced from books. Examples:

    +----------------+----------------------------------------------------------------+
    | Source         | Parent Object                                                  |
    +================+================================================================+
    | book           | book                                                           |
    +----------------+----------------------------------------------------------------+
    | twitter post   | A user's Tweets are considered a "book". E.g the book title    |
    |                | will be "Tweets from @<user>". Each saved post will be a       |
    |                | highlight in that 'book'.                                      |
    +----------------+----------------------------------------------------------------+
    | twitter thread | Individual threads are parents. The "book" title will be       |
    |                | truncated text from the first post.                            |
    +----------------+----------------------------------------------------------------+
    | podcast        | The podcast episode. (The podcast name is the 'author' field.) |
    +----------------+----------------------------------------------------------------+
    | article        | The article.                                                   |
    +----------------+----------------------------------------------------------------+
    | youtube        | Individual videos are treated as an article. (The channel name |
    |                | is the 'author' field).                                        |
    +----------------+----------------------------------------------------------------+

    (Twitter/X is referenced as Twitter, consistent with the Readwise API, March 2025).

    Attributes
    ----------
    user_book_id : int
        Primary key. Unique identifier sourced from Readwise.
    title: str
        The title of the parent object. E.g. Book title, twitter thread first post,
        podcast episode title etc.
    is_ deleted :
        User deleted book. Currently deleted books are stored with non-deleted books:
        handle downstream. No automation alters *highlights* of deleted books - it's
        assumed a deleted book's highlights will be fetched as "updated", with the
        highlights own 'is_deleted' status changed.
    author: str
        The article, tweet or article author, YouTube video creator, podcaster etc.
    readable_title : str
        The title, capitalized and tidied up. Reliably present (2993 out of 2993 sample
        user records).
    source : str
        A single word name for source of the object e.g ``Kindle``, ``twitter``,
        ``api_article`` etc.
    cover_image_url : str
        Link to the cover image. Set automatically by Readwise when highlighting via
        most methods. Seems to use native links where logical (e.g. Amazon, Twitter).
    unique_url : str
        Varies by input method. For example, ``"source": "web_clipper"`` may give a
        link to the original source document (i.e. the same link as ``source_url``).
        ``"source": "reader"`` may give the Readwise Reader link.
    summary : str
        Document summaries can be added in Readwise Reader.
    category : str
        A pre-defined Readwise category. Allowed values: ``books``, ``articles``,
        ``tweets``, ``podcasts``.
    document_note : str
        Can be added in Readwise Reader via the Notebook side panel.
    readwise_url : str
        The Readwise URL link to the "book"/parent object.
    source_url : str
        Link to the URL of the original source, if applicable. E.g. the Twitter account
        of the author, the original article etc.
    asin : str
        Not documented but Amazon Standard Identification Number. Only for Kindle
        highlights.

    batch_id:
        Foreign key linking the ``id`` of the associated ``ReadwiseBatch``.

    book_tags : list[BookTag]
        A list of user defined tags, applied to the parent object. These are distinct
        from highlight tags. (i.e. "arch_btw" could exist separately at a book and
        highlight level).
    highlights : list[Highlight]
        A list of highlights sourced from the book.
    batch : ReadwiseBatch
        The batch object the book was imported in.
    """

    __tablename__ = "books"
    version_class = BookVersion

    user_book_id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("readwise_batches.id"))

    book_tags: Mapped[list["BookTag"]] = relationship(back_populates="book")
    highlights: Mapped[list["Highlight"]] = relationship(back_populates="book")
    batch: Mapped["ReadwiseBatch"] = relationship(back_populates="books")

    def __repr__(self) -> str:
        return (
            f"Book(user_book_id={self.user_book_id!r}, title={self.title!r}, "
            f"highlights={len(self.highlights)})"
        )


class BookTag(Base, ValidationMixin):
    """
    Readwise book tag as a SQL Alchemy ORM Mapped class.

    *WARNING* Using unvalidated API data directly with this class may result in
    unexpected behaviour and is not recommended. Validation is enforced in the Pydantic
    layer only. For example, this ORM class will accept null values for all fields -
    even those fields which should never be null. (Except the primary key which will not
    accept a null).

    Each class instance corresponds to a book tags dictionary from the Readwise
    'Highlight EXPORT' endpoint.

    Attributes
    ----------
    id : int
        Primary key. Unique identifier sourced from Readwise.
    name : str
        The name of the tag. Each tag has an id and name. ``name``s are often common
        across tags/highlights but ``id`` is always unique. E.g. Many highlights may be
        tagged ``favourite`` but each ``favourite`` tag  will be associated with its own
        unique ``id``. Therefore, group by ``name`` for this attribute.

    book_id : int
        Foreign key linking the ``id`` of the associated ``Book``. This can be passed as
        a dictionary key, value or via a book relationship object - but not both.
    batch_id : int
        Foreign key linking the `id` of the associated ``ReadwiseBatch``.

    book : Book
        The highlight object the tag is associated with.
    batch : ReadwiseBatch
        The batch object the tag was imported in.
    """

    __tablename__ = "book_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(512))

    user_book_id: Mapped[int] = mapped_column(
        ForeignKey("books.user_book_id"), nullable=False
    )
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("readwise_batches.id"), nullable=False
    )

    book: Mapped["Book"] = relationship(back_populates="book_tags")
    batch: Mapped["ReadwiseBatch"] = relationship(back_populates="book_tags")

    def __repr__(self) -> str:
        return f"BookTag(name={self.name!r}, id={self.id!r})"


class HighlightBase(Base, ValidationMixin):
    """
    Abstract base class for Highlight fields (excluding relationships).
    """

    __abstract__ = True

    text: Mapped[str] = mapped_column(String(8191))
    location: Mapped[Optional[int]]
    location_type: Mapped[Optional[str]]
    note: Mapped[Optional[str]]
    color: Mapped[Optional[str]]
    highlighted_at: Mapped[Optional[datetime]]
    created_at: Mapped[Optional[datetime]]
    updated_at: Mapped[Optional[datetime]]
    external_id: Mapped[Optional[str]]
    end_location: Mapped[Optional[int]]
    url: Mapped[Optional[str]]
    is_favorite: Mapped[Optional[bool]]
    is_discard: Mapped[Optional[bool]]
    is_deleted: Mapped[Optional[bool]]
    readwise_url: Mapped[Optional[str]]


class HighlightVersion(HighlightBase):
    """
    A version of a highlight with additional fields for versioning.

    This class extends the Highlight class to include versioning information.

    Attributes
    ----------
    version : int
        The version number of the highlight entry.
    """

    __tablename__ = "highlight_versions"
    batch_name = "versioned_highlights"

    version_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version: Mapped[int]
    versioned_at: Mapped[datetime] = mapped_column(default=datetime.now)
    batch_id_when_versioned: Mapped[int] = mapped_column(
        ForeignKey("readwise_batches.id"), nullable=False
    )
    id: Mapped[int] = mapped_column(ForeignKey("highlights.id"))
    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.user_book_id"), nullable=False
    )
    batch_id_when_new: Mapped[int] = mapped_column(
        ForeignKey("readwise_batches.id"), nullable=False
    )

    batch_when_versioned: Mapped["ReadwiseBatch"] = relationship(
        back_populates="versioned_highlights",
        foreign_keys=[batch_id_when_versioned],
    )

    book: Mapped["Book"] = relationship("Book", viewonly=True, foreign_keys=[book_id])

    def __repr__(self) -> str:
        return (
            f"HighlightVersion(id={self.id!r}, book={self.book.title!r}, "
            f"text={self.text[:30]!r}, version={self.version!r})"
        )


class Highlight(HighlightBase):
    """
    Readwise highlight as a SQL Alchemy ORM Mapped class.

    *WARNING* Using unvalidated API data directly with this class may result in
    unexpected behaviour and is not recommended. Validation is enforced in the Pydantic
    layer only. For example, this ORM class will accept null values for all fields -
    even those fields which should never be null. (Except the primary key which will not
    accept a null).

    Each instance corresponds to a highlight dictionary from the Readwise 'Highlight
    EXPORT' endpoint. Highlights are text excerpts saved by the user from books,
    articles, or other sources.

    Attributes
    ----------
    id : int
        Primary key. Unique identifier sourced from Readwise.
    text : str
        The actual highlighted text content. Maximum length is 8191 characters.
    location : int
        Location if applicable. E.g. Kindle location, podcast/YouTube timestamp etc.
    location_type : str
        The type of location e.g. '``offset``, ``time_offset``, ``order``, ``location``,
        ``page`` (there may be others).
    note : str
        User notes added to the highlight.
    color : str
        Highlight color. Colors seen in user data: ``yellow``, ``pink``, ``orange``,
        ``blue``, ``purple``, ``green``.
    highlighted_at : datetime
        Time user made the highlight.
    created_at : datetime
        Time the highlight was added to the database.
    updated_at : datetime
        Time the highlight was edited (assumedly via the Readwise site or API).
    external_id :
        Seems to be the ID of highlight in the source service, where applicable.
        E.g. Readwise, Reader, ibooks, pocket, snipd, airr etc.
    end_location :
        Unknown. Always null in user data samples. Docs only show it as as null.
    url :
        Link to the highlight in the source service, where applicable. E.g. Readwise,
        Reader, ibooks, pocket, snipd, airr etc.
    is_favourite : bool
        User favourites highlight.
    is_discard : bool
        Is discarded by the user, presumably during "Readwise Daily Review".
    is_ deleted : bool
        User deleted highlight. Currently deleted highlights are stored with non-deleted
        highlights. Handle downstream.
    readwise_url :
        The Readwise URL link to the highlight.

    book_id : int
        Foreign key linking the `user_book_id` of the associated `Book`. ``book_id`` is
        the Readwise key name, retained for consistency with the Readwise API.
    batch_id : int
        Foreign key linking the `id` of the associated `ReadwiseBatch`.

    book : Book
        The book the highlight belongs to.
    tags : list[HighlightTag]
        Tags the user has assigned to this highlight.
    batch : ReadwiseBatch
        The batch object the highlight was imported in.
    """

    __tablename__ = "highlights"
    version_class = HighlightVersion

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.user_book_id"), nullable=False
    )
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("readwise_batches.id"), nullable=False
    )

    book: Mapped["Book"] = relationship(back_populates="highlights")
    tags: Mapped[list["HighlightTag"]] = relationship(back_populates="highlight")
    batch: Mapped["ReadwiseBatch"] = relationship(back_populates="highlights")

    def __repr__(self) -> str:
        parts = [f"Highlight(id={self.id!r}"]
        if self.book:
            parts.append(f"book={self.book.title!r}")
        if self.text:
            truncated_highlight_txt = (
                self.text[:30] + "..." if len(self.text) > 30 else self.text
            )
            parts.append(f"text={truncated_highlight_txt!r}")
        else:
            parts.append(f"text={self.text!r}")
        return ", ".join(parts) + ")"


class HighlightTag(Base, ValidationMixin):
    """
    Readwise highlight tag as a SQL Alchemy ORM Mapped class.

    *WARNING* Using unvalidated API data directly with this class may result in
    unexpected behaviour and is not recommended. Validation is enforced in the Pydantic
    layer only. For example, this ORM class will accept null values for all fields -
    even those fields which should never be null. (Except the primary key which will not
    accept a null).

    Each class instance corresponds to a highlight tags dictionary from the Readwise
    'Highlight EXPORT' endpoint.

    Attributes
    ----------
    id : int
        Primary key. Unique identifier sourced from Readwise.
    name : str
        The name of the tag. Each tag has an id and name. ``name``s are often common
        across tags/highlights but ``id`` is always unique. E.g. Many highlights may be
        tagged ``favourite`` but each ``favourite`` tag  will be associated with its own
        unique ``id``. Therefore, group by ``name`` for this attribute.

    highlight_id : int
        Foreign key linking the ``id`` of the associated ``Highlight``.
    batch_id : int
        Foreign key linking the `id` of the associated `ReadwiseBatch`.

    highlight : Highlight
        The highlight object the tag is associated with.
    batch : ReadwiseBatch
        The batch object the tag was imported in.
    """

    __tablename__ = "highlight_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(512))

    highlight_id: Mapped[int] = mapped_column(
        ForeignKey("highlights.id"), nullable=False
    )
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("readwise_batches.id"), nullable=False
    )

    highlight: Mapped["Highlight"] = relationship(back_populates="tags")
    batch: Mapped["ReadwiseBatch"] = relationship(back_populates="highlight_tags")

    def __repr__(self) -> str:
        return f"HighlightTag(name={self.name!r}, id={self.id!r})"


class ReadwiseBatch(Base):
    """
    A batch of database updates from the Readwise API.

    This is not API data, therefore validation is performed here in the ORM layer.

    Attributes
    ----------
    id : int
        Primary key. Auto generated unique identifier for the batch .
    start_time : datetime
        The start time of a fetch from the API.
    end_time : datetime
        The time the fetch completed.
    database_write_time : Optional[datetime]
        The time the batch was written to the database. Can be None if unset but this is
        intended only to allow this attribute to be added last.

    books : list[Book]
        The books included in the batch.
    highlights : list[Highlight]
        The highlights included in the batch.
    highlight_tags : list[HighlightTag]
        The highlight tags included in the batch.
    """

    __tablename__ = "readwise_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    start_time: Mapped[datetime] = mapped_column(nullable=False)
    end_time: Mapped[datetime] = mapped_column(nullable=False)
    database_write_time: Mapped[datetime] = mapped_column(nullable=True)

    books: Mapped[list["Book"]] = relationship(back_populates="batch")
    book_tags: Mapped[list["BookTag"]] = relationship(back_populates="batch")
    highlights: Mapped[list["Highlight"]] = relationship(back_populates="batch")
    highlight_tags: Mapped[list["HighlightTag"]] = relationship(back_populates="batch")

    versioned_books: Mapped[list["BookVersion"]] = relationship(
        back_populates="batch_when_versioned",
        foreign_keys="[BookVersion.batch_id_when_versioned]",
    )
    versioned_highlights: Mapped[list["HighlightVersion"]] = relationship(
        back_populates="batch_when_versioned",
        foreign_keys="[HighlightVersion.batch_id_when_versioned]",
    )

    def __repr__(self) -> str:
        parts = [f"ReadwiseBatch(id={self.id!r}"]
        parts.append(f"books={len(self.books)}")
        parts.append(f"highlights={len(self.highlights)}")
        parts.append(f"book_tags={len(self.book_tags)}")
        parts.append(f"highlight_tags={len(self.highlight_tags)}")
        parts.append(f"versioned_books={len(self.versioned_books)}")
        parts.append(f"versioned_highlights={len(self.versioned_highlights)}")
        if self.start_time:
            parts.append(f"start={self.start_time.isoformat()}")
        if self.end_time:
            parts.append(f"end={self.end_time.isoformat()}")
        if self.database_write_time:
            parts.append(f"write={self.database_write_time.isoformat()}")
        return ", ".join(parts) + ")"


class RoamPage(Base):
    """
    A Roam page highlights have been written to.

    Highlights are expected to be stored under a header which is stored in this table.
    """

    __tablename__ = "roam_pages"

    page_uid: Mapped[str] = mapped_column(primary_key=True)
    highlights_header_uid: Mapped[str] = mapped_column(nullable=False)
    highlights_header_text: Mapped[str] = mapped_column(nullable=False)

    export_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("roam_export_batches.id"), nullable=True
    )
    export_batch: Mapped[Optional["RoamExportBatch"]] = relationship(
        back_populates="pages"
    )

    books: Mapped[list["RoamBookExport"]] = relationship(back_populates="roam_page")
    highlights: Mapped[list["RoamHighlightExport"]] = relationship(
        back_populates="roam_page"
    )
    snapshots: Mapped[list["RoamPageSnapshot"]] = relationship(
        back_populates="roam_page"
    )


class RoamPageSnapshot(Base):
    """
    A JSON snapshot of the books and highlights under the given header.
    """

    __tablename__ = "roam_page_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    page_uid: Mapped[str] = mapped_column(ForeignKey("roam_pages.page_uid"))
    block_tree: Mapped[dict[str, Any]] = mapped_column(JSON)
    block_tree_hash: Mapped[str]
    version: Mapped[int]
    version_date: Mapped[datetime] = mapped_column(default=lambda: datetime.now())

    export_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("roam_export_batches.id"), nullable=True
    )
    export_batch: Mapped[Optional["RoamExportBatch"]] = relationship(
        back_populates="page_snapshots"
    )

    roam_page: Mapped["RoamPage"] = relationship(back_populates="snapshots")


class RoamBookExport(Base):
    """

    Attributes
    ----------
    user_book_id : int

    parent_block_uid : str
        The Roam block id for the book's parent. Highlights
    """

    __tablename__ = "roam_books"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    page_uid: Mapped[str] = mapped_column(
        ForeignKey("roam_pages.page_uid"), nullable=False
    )
    user_book_id: Mapped[int] = mapped_column(
        ForeignKey("books.user_book_id"), nullable=False
    )
    parent_block_uid: Mapped[str] = mapped_column(nullable=False)
    export_date: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(), nullable=False
    )

    export_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("roam_export_batches.id"), nullable=True
    )
    export_batch: Mapped[Optional["RoamExportBatch"]] = relationship(
        back_populates="books"
    )

    roam_page: Mapped["RoamPage"] = relationship(back_populates="books")
    book: Mapped["Book"] = relationship(viewonly=True)


class RoamHighlightExport(Base):
    """
    A record of a highlight being exported into a Roam page.
    """

    __tablename__ = "roam_highlights"

    highlight_id: Mapped[int] = mapped_column(
        ForeignKey("highlights.id"), primary_key=True
    )
    page_uid: Mapped[str] = mapped_column(
        ForeignKey("roam_pages.page_uid"), nullable=False
    )
    block_uid: Mapped[str] = mapped_column(nullable=False)
    export_date: Mapped[datetime] = mapped_column(nullable=False)

    export_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("roam_export_batches.id"), nullable=True
    )
    export_batch: Mapped[Optional["RoamExportBatch"]] = relationship(
        back_populates="highlights"
    )

    roam_page: Mapped["RoamPage"] = relationship(back_populates="highlights")
    highlight: Mapped["Highlight"] = relationship(viewonly=True)
    snapshots: Mapped[list["RoamHighlightSnapshot"]] = relationship(
        back_populates="highlight"
    )


class RoamHighlightSnapshot(Base):
    """
    A snapshot of a highlight block.

    Captures the block attributes and children and their attributes, capturing any
    indented text added under the highlight.

    """

    __tablename__ = "roam_highlight_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    highlight_id: Mapped[int] = mapped_column(
        ForeignKey("roam_highlights.highlight_id")
    )
    block_tree: Mapped[dict[str, Any]] = mapped_column(JSON)
    block_tree_hash: Mapped[str]
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now())

    export_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("roam_export_batches.id"), nullable=True
    )
    export_batch: Mapped[Optional["RoamExportBatch"]] = relationship(
        back_populates="highlight_snapshots"
    )

    highlight: Mapped["RoamHighlightExport"] = relationship(back_populates="snapshots")


class RoamExportBatch(Base):
    """
    A batch of database updates written to Roam.
    """

    __tablename__ = "roam_export_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    database_write_time: Mapped[datetime] = mapped_column(nullable=True)

    pages: Mapped[list["RoamPage"]] = relationship(back_populates="export_batch")
    highlights: Mapped[list["RoamHighlightExport"]] = relationship(
        back_populates="export_batch"
    )
    page_snapshots: Mapped[list["RoamPageSnapshot"]] = relationship(
        back_populates="export_batch"
    )
    highlight_snapshots: Mapped[list["RoamHighlightSnapshot"]] = relationship(
        back_populates="export_batch"
    )
    books: Mapped[list["RoamBookExport"]] = relationship(back_populates="export_batch")

    def __repr__(self) -> str:
        parts = [f"RoamExportBatch(id={self.id!r})"]
        parts.append(f"pages={len(self.pages)}")
        parts.append(f"highlights={len(self.highlights)}")
        parts.append(f"page_snapshots={len(self.page_snapshots)}")
        parts.append(f"highlight_snapshots={len(self.highlight_snapshots)}")
        if self.database_write_time:
            parts.append(f"write={self.database_write_time.isoformat()}")
        return ", ".join(parts) + ")"


class RoamKnownPage(Base):
    """Track daily note pages that are known to exist in Roam."""

    __tablename__ = "roam_known_pages"

    page_uid: Mapped[str] = mapped_column(primary_key=True)
    last_verified_at: Mapped[datetime] = mapped_column(
        default=datetime.now, nullable=False
    )

    def __repr__(self) -> str:
        return f"RoamKnownPage(page_uid={self.page_uid!r})"


class SnipdMetadata(Base):
    """Podcast episode metadata from snipd webpages"""

    __tablename__ = "snipd_metadata"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.user_book_id"), nullable=False
        )
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("readwise_batches.id"), nullable=False
    )

    # stored as a combined strings split with space e.g. a sentence should end '. '.
    # use nltk for sentence splitting on output
    show_notes: Mapped[str] = mapped_column
    #store a string split by newlines
    chapters: Mapped[str] = mapped_column
