import logging
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session

from readwise_local_plus.config import UserConfig
from readwise_local_plus.db_operations import (
    DatabasePopulaterFlattenedData,
    check_database,
    create_database,
    get_last_fetch,
    get_session,
    safe_create_sqlite_engine,
    update_readwise_last_fetch,
)
from readwise_local_plus.models import Base, ReadwiseBatch, ReadwiseLastFetch
from tests.helpers import DbHandle, flat_mock_api_response_fully_validated

logger = logging.getLogger(__name__)

# Reusable mock value
ANYTIME = datetime(2025, 1, 1, 1, 1, 1)


# ----------
#  Fixtures
# ----------


@pytest.fixture()
def mock_book() -> dict:
    return flat_mock_api_response_fully_validated()["books"][0]


@pytest.fixture()
def mock_highlight() -> dict:
    return flat_mock_api_response_fully_validated()["highlights"][0]


@pytest.fixture()
def setup_db(mock_user_config):
    # NOTE: Coupled to upstream functions for ease and table consistency, but beware
    # upstream changes that may affect tests using this fixture.
    engine = safe_create_sqlite_engine(mock_user_config.db_path, echo=False)
    Base.metadata.create_all(engine)
    return mock_user_config.db_path


def add_batch(db_path):
    session = get_session(db_path)
    with session.begin():
        batch = ReadwiseBatch(start_time=ANYTIME, end_time=ANYTIME)
        session.add(batch)
        session.flush()
        return batch, session


# ----------
#  Tests
# ----------


def test_safe_create_sqlite_engine_raises_for_a_missing_foreign_key():
    test_engine = safe_create_sqlite_engine(":memory:")

    class TestBase(DeclarativeBase):
        pass

    class Parent(TestBase):
        __tablename__ = "parent"
        id = Column(Integer, primary_key=True)

    class Child(TestBase):
        __tablename__ = "child"
        id = Column(Integer, primary_key=True)
        parent_id = Column(Integer, ForeignKey("parent.id"))

    TestBase.metadata.create_all(test_engine)
    # We want this to raise because the parent_id doesn't exist in the db.
    with pytest.raises(IntegrityError):
        with Session(test_engine) as session, session.begin():
            session.add(Child(id=1, parent_id=999))


def test_get_session_returns_a_session_object(mock_user_config: UserConfig):
    actual = get_session(mock_user_config.db_path)
    assert isinstance(actual, Session)


def test_get_session_attaches_to_a_database_url(mock_user_config: UserConfig):
    """Test the Session database url has the correct file name."""
    session = get_session(mock_user_config.db_path)
    database_url: str = session.bind.url
    actual = str(database_url).split("/")[-1]
    assert actual == "readwise-local-plus.db"


def test_create_database_tables_created(mock_user_config: UserConfig):
    create_database(mock_user_config.db_path)
    expected = [
        ("books",),
        ("book_tags",),
        ("book_versions",),
        ("highlights",),
        ("highlight_versions",),
        ("highlight_tags",),
        ("readwise_batches",),
        ("readwise_last_fetch",),
        ("roam_books",),
        ("roam_export_batches",),
        ("roam_highlight_snapshots",),
        ("roam_highlights",),
        ("roam_known_pages",),
        ("roam_page_snapshots",),
        ("roam_pages",),
    ]
    connection = sqlite3.connect(mock_user_config.db_path)
    cursor = connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    actual = cursor.fetchall()
    connection.close()
    assert sorted(actual) == sorted(expected)


@patch("readwise_local_plus.db_operations.create_database")
def test_check_database_when_database_doesnt_exist(
    mock_create_database: MagicMock, mock_user_config: UserConfig
):
    actual = check_database(mock_user_config)
    mock_create_database.assert_called_once_with(mock_user_config.db_path)
    assert actual is None


@patch("readwise_local_plus.db_operations.create_database")
@patch("readwise_local_plus.db_operations.get_last_fetch")
def test_check_database_when_database_exists(
    mock_query_last_fetch: MagicMock,
    mock_create_database: MagicMock,
):
    mock_user_config = MagicMock()
    # Mock the database existing.
    mock_user_config.db_path.exists.return_value = True

    mock_last_fetch = datetime(2025, 1, 1, 1, 1, 1)
    mock_query_last_fetch.return_value = mock_last_fetch

    result = check_database(mock_user_config)

    mock_user_config.db_path.exists.assert_called_once()
    mock_query_last_fetch.assert_called_once()
    mock_create_database.assert_not_called()
    assert result == mock_last_fetch


def test_database_populater_flattened_instantiates_with_expected_attrs(
    mem_db: DbHandle,
):
    database_populater = DatabasePopulaterFlattenedData(
        mem_db.session,
        flat_mock_api_response_fully_validated(),
        ANYTIME,
        ANYTIME,
    )
    assert list(database_populater.__dict__.keys()) == [
        "session",
        "validated_flattened_objs",
        "start_fetch",
        "end_fetch",
        "_batch",
    ]
    assert database_populater.ORM_TABLE_MAP is not None


def test_update_readwise_last_fetch(mem_db: DbHandle):
    mock_fetches = [
        datetime(2025, 1, 1, 1, 1, 1),
        datetime(2025, 1, 1, 2, 2, 2),
    ]
    for mock_fetch in mock_fetches:
        update_readwise_last_fetch(mem_db.session, start_current_fetch=mock_fetch)
        mem_db.session.commit()

        actual_record = mem_db.session.get(ReadwiseLastFetch, 1)
        assert actual_record.last_successful_fetch == mock_fetch

        total_records = mem_db.session.query(ReadwiseLastFetch).count()
        assert total_records == 1


def test_get_last_fetch_returns_none_if_no_entry(mem_db: DbHandle):
    last_fetch = get_last_fetch(mem_db.session)
    assert last_fetch is None


def test_get_last_fetch_returns_datetime_if_entry_exists(mem_db: DbHandle):
    mock_last_start_fetch = datetime(2025, 1, 1, 1, 1, 1)
    # Beware coupling to the upstream function.
    update_readwise_last_fetch(
        mem_db.session, start_current_fetch=mock_last_start_fetch
    )
    last_fetch = get_last_fetch(mem_db.session)
    assert last_fetch == mock_last_start_fetch
