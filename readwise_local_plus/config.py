import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


class MissingEnvironmentFile(Exception):
    """Custom exception if environment file not available."""

    pass


class UserConfig:
    """Object containing user configuration information."""

    def __init__(self, user_dir: Path) -> None:
        """
        Initialise object. DO NOT USE DIRECTLY, use `fetch_user_config()` instead.

        Attributes
        ----------
        user_dir : pathlib.Path, default = ``Path.home()``
            The user's home directory.
        app_dir : pathlib.Path
            The application directory where the database/log files etc. are stored.
        log_path : pathlib.Path
            The path to the log file.
        config_dir : pathlib.Path
            The directory for configuration files, set to
            ``~/.config/readwise-local-plus``.
        env_file : pathlib.Path
            The path to the environment variables file in the config_dir, set to
            ``~/.config/readwise-local-plus/.env``.
        readwise_api_token : str | None
            The Readwise API token loaded from the environment variables.
        db_path : pathlib.Path
            The path to the SQLite database file, defaults to
            ``~/.readwise-local-plus/readwise.db``.
        """
        self.user_dir = user_dir
        self.app_dir: Path = user_dir / "readwise-local-plus"
        self.app_dir.mkdir(exist_ok=True, parents=True)
        self.log_path = self.app_dir / "logs" / "app.log"
        self.config_dir = user_dir / ".config" / "readwise-local-plus"
        self.env_file: Path = self.config_dir / ".env"
        self.db_path: Path = self.app_dir / "readwise-local-plus.db"
        self.load_environment_variables_file()
        self.readwise_api_token: str | None = os.getenv("READWISE_API_TOKEN")
        self.roam_api_token: str | None = os.getenv("ROAM_API_TOKEN")
        self.roam_graph_name: str = "Billowz"

    def load_environment_variables_file(self) -> None:
        """
        Load the `.env` file.

        Raises
        ------
        MissingEnvironmentFile
            If the .env file is not in the expected location.
        """
        if self.env_file.exists():
            load_dotenv(self.env_file, override=True)
        else:
            raise MissingEnvironmentFile(
                "A '.env' file is expected in the '~/.config/readwise-local-plus' "
                "directory."
            )


@lru_cache()
def fetch_user_config(user_dir: Path = Path.home()) -> UserConfig:
    """
    Fetch the user configuration.

    Memoize to ensure a single instance of UserConfig is used throughout the
    application.

    Returns
    -------
    UserConfig
        The user configuration object.
    """
    return UserConfig(user_dir)
