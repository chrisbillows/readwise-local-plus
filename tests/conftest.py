"""
Pytest fixtures.

Helper classes and functions should be placed either in their own module or, if used
in multiple test modules, in the `tests/helpers.py` module.

"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import sessionmaker

from readwise_local_plus.config import UserConfig
from readwise_local_plus.db_operations import safe_create_sqlite_engine
from readwise_local_plus.models import Base
from tests.helpers import DbHandle


@pytest.fixture
def mock_user_config(tmp_path: pytest.TempPathFactory) -> UserConfig:
    """
    Return a temporary user configuration.

    This is function scoped version.

    Use a `tmp_path` as the User's home directory. Create the directory and create the
    required .env file with required synthetic data.
    """
    temp_application_dir = tmp_path / "readwise-local-plus"
    temp_application_dir.mkdir()
    temp_config_dir = temp_application_dir / ".config" / "readwise-local-plus"
    temp_config_dir.mkdir(parents=True)

    temp_env_file = temp_config_dir / ".env"
    temp_env_file.touch()
    temp_env_file.write_text("READWISE_API_TOKEN = 'abc123'")
    user_config = UserConfig(temp_application_dir)
    return user_config


@pytest.fixture(scope="module")
def mock_user_config_module_scoped(
    tmp_path_factory: pytest.TempPathFactory,
) -> UserConfig:
    """
    Return a temporary user configuration.

    Use a `tmp_path` as the User's home directory. Create the directory and create the
    required .env file with required synthetic data.
    """
    temp_application_dir = tmp_path_factory.mktemp("readwise-local-plus")
    temp_config_dir = temp_application_dir / ".config" / "readwise-local-plus"
    temp_config_dir.mkdir(parents=True)

    temp_env_file = temp_config_dir / ".env"
    temp_env_file.touch()
    temp_env_file.write_text("READWISE_API_TOKEN = 'abc123'")
    user_config = UserConfig(temp_application_dir)
    return user_config


@pytest.fixture()
def mem_db() -> Generator["DbHandle"]:
    """
    Create an in-memory SQLite database and return an engine and session.

    Creates tables for all ORM mapped classes that inherit from Base.
    """
    engine = safe_create_sqlite_engine(":memory:", echo=False)
    Base.metadata.create_all(engine)
    # This isn't needed. It's included as a best practice example or for future use.
    SessionMaker = sessionmaker(bind=engine)
    session = SessionMaker()
    yield DbHandle(engine, session)
    session.close()
