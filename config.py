"""Read configuration and a real encryption secret from a local .env file."""

from dataclasses import dataclass, field
import math
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent


class ConfigurationError(ValueError):
    """A user-actionable error that does not contain a secret value."""


@dataclass(frozen=True)
class Settings:
    db_path: Path
    rate_limit: int
    rate_window: float
    data_key: str = field(repr=False)


def load_settings(env_file: Path = ROOT / ".env") -> Settings:
    env_file = env_file.resolve()
    if not env_file.is_file():
        raise ConfigurationError("Missing .env. Run python init_local.py first.")
    # Adapted from python-dotenv: load a dict WITHOUT changing system variables.
    # https://bbc2.github.io/python-dotenv/#load-configuration-without-altering-the-environment
    # Path supplies the explicit file location; interpolation is disabled so a
    # secret cannot be substituted from an operating-system environment variable.
    values = dotenv_values(env_file, interpolate=False)
    key = values.get("TASK_DATA_KEY") or ""
    try:
        Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError):
        raise ConfigurationError("Invalid TASK_DATA_KEY in .env; the key value is not displayed.") from None
    try:
        limit = int(values.get("TASK_RATE_LIMIT") or "10")
        window = float(values.get("TASK_RATE_WINDOW_SECONDS") or "60")
        if not 1 <= limit <= 10000 or not math.isfinite(window) or not 0 < window <= 3600:
            raise ValueError
    except ValueError:
        raise ConfigurationError("Rate limit must be 1-10000 and the window must be within (0, 3600] seconds.") from None
    db_path = Path(values.get("TASK_DB_PATH") or "data/assignments_secure.db")
    if not db_path.is_absolute():
        db_path = env_file.parent / db_path
    return Settings(db_path.resolve(), limit, window, key)
