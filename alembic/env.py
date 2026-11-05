"""Alembic environment using the Runner's canonical SQLite resolver."""

from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import URL, create_engine, event
from sqlalchemy.pool import NullPool

config = context.config
if (
    config.config_file_name
    and config.get_section("loggers") is not None
):
    fileConfig(config.config_file_name)

target_metadata = None
ROOT = Path(__file__).resolve().parents[1]


def _database_url() -> str:
    from lib.repositories.database_config import resolve_database_path

    path = resolve_database_path(project_root=ROOT)
    return URL.create("sqlite", database=str(path)).render_as_string(
        hide_password=False
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _configure_connection(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied = config.attributes.get("connection")
    if supplied is not None:
        _configure_connection(supplied)
        return

    engine = create_engine(
        _database_url(),
        poolclass=NullPool,
        connect_args={"timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    try:
        with engine.connect() as connection:
            _configure_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
