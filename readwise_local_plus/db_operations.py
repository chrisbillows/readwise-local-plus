"""
Logic for interacting with the database.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Type, Union, cast

from sqlalchemy import Engine, create_engine, desc, event, select
from sqlalchemy.orm import Session, class_mapper, sessionmaker

from readwise_local_plus.config import UserConfig, fetch_user_config
from readwise_local_plus.models import (
    Base,
    Book,
    BookTag,
    Highlight,
    HighlightTag,
    ReadwiseBatch,
    ReadwiseLastFetch,
)
from readwise_local_plus.types import ReadwiseAPIObject

logger = logging.getLogger(__name__)


def safe_create_sqlite_engine(
    sqlite_database: Union[str, Path], echo: bool = False
) -> Engine:
    """
    Create a SQLite engine with foreign key enforcement enabled for all connections.

    Foreign key constraints are not enforced by default in SQLite. They must be
    enabled for every new database connection using the ``PRAGMA foreign_keys=ON``
    statement, as PRAGMA settings do not persist in the database file. This function
    creates a SQLAlchemy ``Engine`` configured with an event listener that ensures
    this PRAGMA statement is always executed.

    Create SQLite engines with this function to ensure consistent foreign key behaviour.
    For more details, see:
    https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#foreign-key-support

    Parameters
    ----------
    sqlite_database : Union[str, Path]
        The filename of the SQLite database file, or ':memory:' for an in-memory
        database.
    echo : bool, optional
        If ``True``, SQLAlchemy will log all SQL statements (default is ``False``).

    Returns
    -------
    Engine
        A SQLAlchemy ``Engine`` instance that will enforce foreign key constraints
        on all connections.
    """

    def set_sqlite_pragma(
        dbapi_connection: sqlite3.Connection, connection_record: Any
    ) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    db_path = "sqlite:///" + str(sqlite_database)
    engine = create_engine(db_path, echo=echo)
    event.listen(engine, "connect", set_sqlite_pragma)
    return engine


def get_session(database_path: str | Path) -> Session:
    """
    Establish a connection to the database and return a session.

    Parameters
    ----------
    database_path : str
    """
    engine = safe_create_sqlite_engine(database_path)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    return session


def create_database(database_path: str | Path) -> None:
    """Create the database schema. This should only be called during setup."""
    engine = safe_create_sqlite_engine(database_path)
    Base.metadata.create_all(engine)


def check_database(user_config: Optional[UserConfig] = None) -> None | datetime:
    """
    If the db exists, return the last fetch time, otherwise create the db.

    Parameters
    ----------
    user_config: UserConfig, default = fetch_user_config()
        A User Config object.

    Returns
    -------
    None | datetime
        None if the database doesn't exist. If the database exists, the time the last
        fetch was completed as a datetime object.
    """
    if user_config is None:
        user_config = fetch_user_config()

    if user_config.db_path.exists():
        logger.info("Database exists")
        session = get_session(user_config.db_path)
        last_fetch = get_last_fetch(session)
        session.close()
        logger.info(f"Last fetch: {last_fetch}")
        return last_fetch
    else:
        logger.info(f"Creating database at {user_config.db_path}")
        create_database(user_config.db_path)
        return None


class DatabasePopulaterFlattenedData:
    """
    Class to populate the database with flattened data from Readwise API responses.

    Attributes
    ----------
    READWISE_API_OBJECTS : list[Type[Base]]
        A list of Readwise API objects that are used to populate the database.
    ORM_TABLE_MAP : dict[str, Type[Base]]
        A mapping of object type names to their corresponding ORM model classes.
    """

    READWISE_API_OBJECTS = [Book, BookTag, Highlight, HighlightTag]
    ORM_TABLE_MAP: dict[str, Type[Base]] = {
        cls.__tablename__: cls for cls in READWISE_API_OBJECTS
    }

    def __init__(
        self,
        session: Session,
        validated_flattened_objs: dict[str, list[dict[str, Any]]],
        start_fetch: datetime,
        end_fetch: datetime,
    ):
        """Initialiser.

        Parameters
        ----------
        session: Session
            An SQL Alchemy session.
        validated_flattened_objs: dict[str, list[dict[str, Any]]]
            The flattened API data with each object having additional validation fields.
            The dict keys are the object type (books, book_tags etc) and values for each
            are a list of that type of object.
        start_fetch: datetime
            The time when the API fetch was started.
        end_fetch: datetime
            The time when the API fetch was completed.

        Attributes
        ----------
        batch: ReadwiseBatch
            A ReadwiseBatch object representing the current batch of data being
            processed. This is created only when an object is found that needs to be
            added to the session.
        """
        self.session = session
        self.validated_flattened_objs = validated_flattened_objs
        self.start_fetch = start_fetch
        self.end_fetch = end_fetch
        self._batch: ReadwiseBatch | None = None

    @property
    def batch(self) -> ReadwiseBatch:
        """
        The ReadwiseBatch object representing the current batch of data being processed.

        Batches are only created when an object is found that needs to be added to the
        session.

        Raises
        ------
        RuntimeError
            If the batch property is invoked before it has been set.

        Returns
        -------
        ReadwiseBatch
            The ReadwiseBatch object for the current session.
        """
        if self._batch is None:
            raise RuntimeError(
                "Batch has not been set. Call _ensure_batch() to create it."
            )
        return self._batch

    def _ensure_batch(self) -> None:
        """
        Ensure that a ReadwiseBatch object exists for the current session.

        If it does not exist, create a new one with the start and end fetch times. Use
        this method before adding any objects to the session.
        """
        if self._batch is None:
            self._batch = ReadwiseBatch(
                start_time=self.start_fetch,
                end_time=self.end_fetch,
                database_write_time=datetime.now(tz=timezone.utc),
            )
            self.session.add(self._batch)

    def populate_database(self) -> int | None:
        """
        Populate the database with objects from a Readwise API response.

        Readwise highlights are exported as books, with each book containing a list
        of highlights. If specified, only highlights created since the 'last_fetch' date
        are included. i.e. A book might have 100 highlights, but if only 1 highlight has
        been added since the last fetch, only 1 highlight will be in the highlights
        list.

        Return
        ------
        ReadwiseBatch | None
            The batch id just written or None if no writeable highlights
            were found.
        """
        for obj_name, raw_objs in self.validated_flattened_objs.items():
            orm_model = self.ORM_TABLE_MAP[obj_name]
            for raw_obj in raw_objs:
                self._process_obj(raw_obj, orm_model)
        if self._batch is None:
            return None
        return self._batch.id

    def _process_obj(self, raw_obj: dict[str, Any], orm_model: Type[Base]) -> None:
        """
        Process objects into the database.

        Create a new ORM instance or update an existing one and, optionally, create a
        version snapshot if the object is versionable.

        Parameters
        ----------
        raw_obj : dict[str, Any]
            The raw object data to be processed.
        orm_model : Type[Base]
            The ORM model class to which the raw object should be mapped.
        """
        obj_pk_field = class_mapper(orm_model).primary_key[0].name
        raw_obj_pk_value = raw_obj[obj_pk_field]
        existing_obj = cast(
            ReadwiseAPIObject, self.session.get(orm_model, raw_obj_pk_value)
        )

        if not existing_obj:
            # Object is brand new.
            self._ensure_batch()
            obj_as_orm = orm_model(**raw_obj, batch=self._batch)
            self.session.add(obj_as_orm)
        else:
            # Object already exists.
            if not self._existing_obj_is_duplicate(existing_obj, raw_obj):
                self._ensure_batch()
                self._version_existing_obj_if_versionable(
                    existing_obj,
                    obj_pk_field,
                    raw_obj_pk_value,
                    orm_model,
                )
                # Object has changed // Update existing object.
                self._add_updated_obj_to_session(existing_obj, raw_obj)

            else:
                # Object has not changed. // Do nothing.
                pass

    def _existing_obj_is_duplicate(
        self, existing_obj: ReadwiseAPIObject, raw_obj: dict[str, Any]
    ) -> bool:
        """
        Check if the object is an exact duplicate based on all fields.

        This is to be expected for overlapping API fetches and also for books included
        only because they have new highlights, or book tags or highlight tags which
        are connected to an altered object.

        Parameters
        ----------
        existing_obj : ReadwiseAPIObject
            The existing ORM object to check against.
        raw_obj : dict[str, Any]
            The raw object data to compare with the existing object.

        Returns
        -------
        bool
            True if the object is a duplicate, False otherwise.
        """
        existing_data = existing_obj.dump_column_data(exclude={"batch_id"})
        return existing_data == raw_obj

    def _version_existing_obj_if_versionable(
        self,
        existing_obj: ReadwiseAPIObject,
        obj_pk_field: str,
        raw_obj_pk_value: int,
        orm_model: Type[Base],
    ) -> None:
        """
        Create a version snapshot if the object is versionable.

        Parameters
        ----------
        existing_obj : ReadwiseAPIObject
            The existing ORM object.
        obj_pk_field : str
            The primary key field of the ORM model.
        raw_obj_pk_value : int
            The primary key value of the raw object.
        orm_model : Type[Base]
            The ORM model class of the existing object.
        """
        if hasattr(orm_model, "version_class"):
            version_num = self._iterate_version_number(
                orm_model, obj_pk_field, raw_obj_pk_value
            )
            version_model = orm_model.version_class
            version_snapshot_orm = version_model(
                **existing_obj.dump_column_data(exclude={"batch_id"}),
                version=version_num,
                batch_id_when_new=existing_obj.batch_id,
                batch_when_versioned=self._batch,
            )
            self.session.add(version_snapshot_orm)

    def _add_updated_obj_to_session(
        self,
        existing_obj: ReadwiseAPIObject,
        raw_obj: dict[str, Any],
    ) -> None:
        """
        Update the existing object with changed data and add to the session.

        Parameters
        ----------
        existing_obj : ReadwiseAPIObject
            The existing ORM object to update.
        raw_obj : dict[str, Any]
            The raw object data to update the existing object with.
        """
        for field, value in raw_obj.items():
            setattr(existing_obj, field, value)
        if self._batch is not None:
            existing_obj.batch = self._batch
        self.session.add(existing_obj)

    def _iterate_version_number(
        self, version_model: Type[Base], version_pk_attr: str, raw_obj_pk: Any
    ) -> int:
        """
        Get the next version number for a versionable object.

        Parameters
        ----------
        version_model : Type[Base]
            The ORM model class for the versionable object.
        version_pk_attr : str
            The primary key attribute of the version model.
        raw_obj_pk : Any
            The primary key value of the raw object to check for existing versions.
        """
        stmt = select(version_model).where(version_pk_attr == raw_obj_pk)
        previous_entries = self.session.execute(stmt).scalars().all()
        version_num = len(previous_entries) + 1
        return version_num


def update_readwise_last_fetch(session: Session, start_current_fetch: datetime) -> None:
    """
    Update the readwise_last_fetch table with the start and end fetch times.

    This will overwrite the existing entry with id=1, or create a new one if it does not
    exist.

    Parameters
    ----------
    session: Session
        A SQL alchemy session connected to a database.
    start_current_fetch: datetime
        The time the fetch was called.
    """
    logger.info("Updating Readwise Last Fetch table")
    existing = session.get(ReadwiseLastFetch, 1)
    if existing:
        existing.last_successful_fetch = start_current_fetch
    else:
        existing = ReadwiseLastFetch(id=1, last_successful_fetch=start_current_fetch)
        session.add(existing)


def get_last_fetch(session: Session) -> datetime | None:
    """
    Get the UTC time of the last Readwise API fetch from the database.

    The 'last fetch' uses the *start* time of the previous fetch, to allow for an
    overlap.

    Parameters
    ----------
    session: Session
        A SQL alchemy session connected to a database.

    Returns
    -------
    datetime | None
        A datetime object representing the UTC start time of the last fetch, or None.
    """
    # Only a single entry is expected in the ReadwiseLastFetch table.
    logger.info("Fetching last Readwise fetch time from database")
    stmt = (
        select(ReadwiseLastFetch)
        .order_by(desc(ReadwiseLastFetch.last_successful_fetch))
        .limit(1)
    )
    result = session.execute(stmt).scalars().first()
    last_fetch = result.last_successful_fetch if result else None
    return last_fetch
