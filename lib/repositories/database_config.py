"""Canonical SQLite database path resolution for the local Runner."""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Mapping
from urllib.parse import unquote


class DatabaseConfigurationError(ValueError):
    """Raised when database path settings are ambiguous or unsupported."""


_DEFAULT_DATABASE = Path("results") / "test_results.db"
_SQLITE_URL_PREFIXES = ("sqlite+pysqlite:///", "sqlite:///")


def _load_secure_dotenv(root: Path) -> None:
    """Load a private repository .env without overriding explicit process values."""
    env_file = root / ".env"
    if env_file.is_symlink():
        raise DatabaseConfigurationError(".env must be a regular file, not a symlink")
    if not env_file.is_file():
        return
    mode = stat.S_IMODE(env_file.stat().st_mode)
    if mode & 0o077:
        raise DatabaseConfigurationError(".env must be owner-readable only; restrict its permissions")
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise DatabaseConfigurationError("python-dotenv is required to load the private .env file") from exc
    try:
        load_dotenv(dotenv_path=env_file, override=False)
    except OSError as exc:
        raise DatabaseConfigurationError(f"unable to read .env: {type(exc).__name__}") from exc


def _normalise_path(value: str | Path) -> Path:
    raw = os.fspath(value).strip()
    if not raw:
        raise DatabaseConfigurationError("database path must not be empty")
    if raw == ":memory:":
        raise DatabaseConfigurationError(
            "in-memory SQLite is unsupported because Runner repositories use independent connections; "
            "configure a file-backed database path"
        )
    return Path(raw).expanduser()


def _comparison_key(path: Path) -> str:
    return str(path.resolve(strict=False))


def _sqlite_url_path(database_url: str) -> str:
    prefix = next((item for item in _SQLITE_URL_PREFIXES if database_url.startswith(item)), None)
    if prefix is None:
        raise DatabaseConfigurationError(
            "DATABASE_URL must use a synchronous SQLite URL in the Runner phase "
            "(sqlite:/// or sqlite+pysqlite:///); other database engines are not enabled"
        )
    raw_path = database_url[len(prefix):]
    if not raw_path or "?" in raw_path or "#" in raw_path:
        raise DatabaseConfigurationError(
            "DATABASE_URL must contain a SQLite database path without query or fragment options"
        )
    decoded = unquote(raw_path)
    if not decoded:
        raise DatabaseConfigurationError("DATABASE_URL contains an empty SQLite path")
    return decoded


def resolve_database_path(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    project_root: str | Path | None = None,
) -> Path:
    """Resolve one SQLite path using explicit, environment, URL and default precedence.

    Precedence is: explicit argument; NETREGRESS_DATABASE_PATH (with TEST_DB_PATH
    retained as a compatibility alias); SQLite DATABASE_URL; repository default.
    If both path environment variables are set they must identify the same file.
    Relative explicit/environment/URL paths retain the process working-directory
    semantics used by existing CLI invocations.
    """
    root = Path(project_root or Path(__file__).resolve().parents[2]).expanduser().resolve(strict=False)
    if path is not None:
        return _normalise_path(path)
    if environ is None:
        _load_secure_dotenv(root)

    env = os.environ if environ is None else environ
    canonical = (env.get("NETREGRESS_DATABASE_PATH") or "").strip()
    legacy = (env.get("TEST_DB_PATH") or "").strip()
    if canonical and legacy:
        canonical_path = _normalise_path(canonical)
        legacy_path = _normalise_path(legacy)
        if _comparison_key(canonical_path) != _comparison_key(legacy_path):
            raise DatabaseConfigurationError(
                "NETREGRESS_DATABASE_PATH and TEST_DB_PATH point to different files; "
                "set only NETREGRESS_DATABASE_PATH or make both values identical"
            )
        return canonical_path
    if canonical or legacy:
        return _normalise_path(canonical or legacy)

    database_url = (env.get("DATABASE_URL") or "").strip()
    if database_url:
        return _normalise_path(_sqlite_url_path(database_url))

    return root / _DEFAULT_DATABASE
