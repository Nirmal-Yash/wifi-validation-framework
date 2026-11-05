"""Alembic migration, integrity, backup and schema-drift governance for SQLite."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL, create_engine, event
from sqlalchemy.pool import NullPool

from lib.services.operational_recovery import SQLiteBackupService
from .schema_contract import SchemaDriftReport, inspect_sqlite_schema


class DatabaseMigrationError(RuntimeError):
    """Raised when a database cannot be safely upgraded or restored."""


class DatabaseSchemaDriftError(DatabaseMigrationError):
    """Raised when a database does not match the single Alembic head."""


class MultipleMigrationHeadsError(DatabaseMigrationError):
    """Raised when the repository contains more than one Alembic head."""


@dataclass(frozen=True, slots=True)
class DatabaseMigrationStatus:
    database_path: Path
    current_revision: str | None
    head_revision: str
    is_up_to_date: bool
    schema: SchemaDriftReport
    last_backup: Path | None = None

    def as_dict(self) -> dict:
        return {
            "database_path": str(self.database_path),
            "current_revision": self.current_revision,
            "head_revision": self.head_revision,
            "is_up_to_date": self.is_up_to_date,
            "schema": self.schema.as_dict(),
            "last_backup": str(self.last_backup) if self.last_backup else None,
        }


class DatabaseMigrationManager:
    """Own all schema changes through Alembic, with pre-upgrade recovery.

    Application code calls upgrade() during SQLiteDatabase.initialize().
    Read-only status/check commands never run migrations. Schema drift is
    reported rather than repaired outside a versioned revision.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        project_root: str | Path | None = None,
        backup_service: SQLiteBackupService | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve(strict=False)
        self.project_root = Path(
            project_root or Path(__file__).resolve().parents[2]
        ).expanduser().resolve(strict=False)
        self.backup_service = backup_service or SQLiteBackupService()

    def _config(self) -> Config:
        config = Config(str(self.project_root / "alembic.ini"))
        config.set_main_option("script_location", str(self.project_root / "alembic"))
        return config

    def _script(self) -> ScriptDirectory:
        script = ScriptDirectory.from_config(self._config())
        heads = script.get_heads()
        if len(heads) != 1:
            raise MultipleMigrationHeadsError(
                f"expected one Alembic head, found {len(heads)}: {heads}"
            )
        return script

    @contextmanager
    def _maintenance_lock(self) -> Iterator[None]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.database_path.with_name(self.database_path.name + ".migration.lock")
        handle = lock_path.open("a+b")
        try:
            try:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except ImportError:
                # The Runner's supported deployment uses Linux. The fallback
                # retains an in-process lock for platforms without fcntl.
                import threading
                lock = _fallback_lock(lock_path)
                lock.acquire()
                try:
                    yield
                finally:
                    lock.release()
                return
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass
            handle.close()

    def _current_revision(self, script: ScriptDirectory | None = None) -> str | None:
        if not self.database_path.is_file() or self.database_path.stat().st_size == 0:
            return None
        connection = sqlite3.connect(self.database_path)
        try:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            if not exists:
                return None
            rows = connection.execute(
                "SELECT version_num FROM alembic_version ORDER BY version_num"
            ).fetchall()
        finally:
            connection.close()
        revisions = [row[0] for row in rows]
        if not revisions:
            return None
        if len(revisions) != 1:
            raise MultipleMigrationHeadsError(
                f"database records multiple Alembic revisions: {revisions}"
            )
        current = revisions[0]
        script = script or self._script()
        try:
            known_revision = script.get_revision(current)
        except Exception as exc:
            raise DatabaseMigrationError(
                f"database revision {current!r} is not present in this repository; "
                "restore a compatible backup or supply the missing migration history"
            ) from exc
        if known_revision is None:
            raise DatabaseMigrationError(
                f"database revision {current!r} is not present in this repository; "
                "restore a compatible backup or supply the missing migration history"
            )
        return current

    def _integrity_check(self) -> None:
        if not self.database_path.is_file() or self.database_path.stat().st_size == 0:
            return
        try:
            connection = sqlite3.connect(self.database_path, timeout=10)
            try:
                result = connection.execute("PRAGMA integrity_check").fetchone()
                if result is None or result[0] != "ok":
                    raise DatabaseMigrationError(
                        f"SQLite integrity_check failed: {result[0] if result else 'no result'}"
                    )
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            raise DatabaseMigrationError(
                f"database is not a readable SQLite file: {exc}"
            ) from exc

    def _inspect(self, script: ScriptDirectory | None = None) -> DatabaseMigrationStatus:
        script = script or self._script()
        head = script.get_current_head()
        current = self._current_revision(script)
        if not self.database_path.is_file():
            schema = SchemaDriftReport(
                metadata_errors=(f"database file does not exist: {self.database_path}",)
            )
        else:
            try:
                connection = sqlite3.connect(self.database_path, timeout=10)
                try:
                    schema = inspect_sqlite_schema(
                        connection,
                        current_revision=current,
                        head_revision=head,
                    )
                finally:
                    connection.close()
            except sqlite3.DatabaseError as exc:
                schema = SchemaDriftReport(
                    metadata_errors=(f"schema inspection failed: {exc}",)
                )
        return DatabaseMigrationStatus(
            database_path=self.database_path,
            current_revision=current,
            head_revision=head,
            is_up_to_date=current == head and schema.is_clean,
            schema=schema,
        )

    def check(self) -> DatabaseMigrationStatus:
        """Inspect revision and physical schema without changing the database."""
        return self._inspect()

    def _run_alembic_upgrade(self, target: str = "head") -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        url = URL.create("sqlite", database=str(self.database_path))
        engine = create_engine(
            url,
            poolclass=NullPool,
            connect_args={"timeout": 15},
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.execute("PRAGMA legacy_alter_table=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        try:
            with engine.connect() as connection:
                config = self._config()
                config.attributes["connection"] = connection
                command.upgrade(config, target)
        finally:
            engine.dispose()

    def _automatic_backup_path(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_dir = self.database_path.parent / "backups"
        return backup_dir / f"{self.database_path.name}.pre-migration-{stamp}.sqlite"

    def upgrade(self) -> DatabaseMigrationStatus:
        """Back up an existing database, upgrade it, verify it, and roll back on failure."""
        with self._maintenance_lock():
            script = self._script()
            self._integrity_check()
            status = self._inspect(script)
            if status.is_up_to_date:
                return status

            had_database = (
                self.database_path.is_file() and self.database_path.stat().st_size > 0
            )
            backup_path = None
            if had_database:
                backup_path = self._automatic_backup_path()
                backup_result = self.backup_service.backup(
                    self.database_path, backup_path
                )
                if not backup_result.integrity_ok:
                    raise DatabaseMigrationError(
                        f"pre-migration backup failed integrity verification: {backup_path}"
                    )

            try:
                self._run_alembic_upgrade("head")
                self._integrity_check()
                final_status = self._inspect(script)
                if not final_status.is_up_to_date:
                    raise DatabaseSchemaDriftError(
                        json.dumps(final_status.as_dict(), indent=2, sort_keys=True)
                    )
                return DatabaseMigrationStatus(
                    database_path=final_status.database_path,
                    current_revision=final_status.current_revision,
                    head_revision=final_status.head_revision,
                    is_up_to_date=final_status.is_up_to_date,
                    schema=final_status.schema,
                    last_backup=backup_path,
                )
            except Exception as exc:
                recovery_message = "no pre-migration backup was required"
                if backup_path is not None:
                    try:
                        restored = self.backup_service.restore(
                            backup_path, self.database_path
                        )
                        if not restored.integrity_ok:
                            raise DatabaseMigrationError(
                                "restored database did not pass integrity_check"
                            )
                        recovery_message = f"restored from {backup_path}"
                    except Exception as restore_error:
                        recovery_message = (
                            f"automatic recovery FAILED from {backup_path}: {restore_error}"
                        )
                else:
                    try:
                        for suffix in ("", "-wal", "-shm"):
                            incomplete = Path(str(self.database_path) + suffix)
                            if incomplete.exists():
                                incomplete.unlink()
                        recovery_message = "removed the incomplete fresh database and SQLite sidecars"
                    except OSError as remove_error:
                        recovery_message = f"could not remove incomplete fresh database: {remove_error}"
                raise DatabaseMigrationError(
                    f"Alembic upgrade failed ({exc}); recovery result: {recovery_message}"
                ) from exc

    def backup(self, destination: str | Path | None = None):
        with self._maintenance_lock():
            self._integrity_check()
            if not self.database_path.is_file():
                raise FileNotFoundError(self.database_path)
            if destination is None:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                destination = (
                    self.database_path.parent
                    / "backups"
                    / f"{self.database_path.name}.manual-{stamp}.sqlite"
                )
            return self.backup_service.backup(self.database_path, destination)

    def restore(self, backup: str | Path, *, create_pre_restore_backup: bool = True) -> dict:
        """Restore a verified SQLite backup; stop Runner processes before invoking."""
        backup_path = Path(backup).expanduser().resolve(strict=False)
        if not backup_path.is_file():
            raise FileNotFoundError(backup_path)
        with self._maintenance_lock():
            source = sqlite3.connect(backup_path)
            try:
                result = source.execute("PRAGMA integrity_check").fetchone()
                if result is None or result[0] != "ok":
                    raise DatabaseMigrationError(
                        f"backup integrity_check failed: {result[0] if result else 'no result'}"
                    )
                has_version_table = source.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
                ).fetchone()
                backup_revision = None
                if has_version_table:
                    rows = source.execute(
                        "SELECT version_num FROM alembic_version ORDER BY version_num"
                    ).fetchall()
                    if len(rows) > 1:
                        raise MultipleMigrationHeadsError(
                            f"backup records multiple Alembic revisions: {[row[0] for row in rows]}"
                        )
                    backup_revision = rows[0][0] if rows else None
            finally:
                source.close()

            script = self._script()
            if backup_revision is not None and script.get_revision(backup_revision) is None:
                raise DatabaseMigrationError(
                    f"backup revision {backup_revision!r} is not supported by this repository"
                )

            pre_restore_backup = None
            if (
                create_pre_restore_backup
                and self.database_path.is_file()
                and self.database_path.stat().st_size > 0
            ):
                pre_restore_backup = self._automatic_backup_path()
                result = self.backup_service.backup(
                    self.database_path, pre_restore_backup
                )
                if not result.integrity_ok:
                    raise DatabaseMigrationError("pre-restore backup failed integrity verification")

            restored = self.backup_service.restore(
                backup_path, self.database_path
            )
            if not restored.integrity_ok:
                raise DatabaseMigrationError("restored database failed integrity verification")
            return {
                "database_path": str(self.database_path),
                "backup_path": str(backup_path),
                "backup_revision": backup_revision,
                "pre_restore_backup": (
                    str(pre_restore_backup) if pre_restore_backup else None
                ),
                "integrity_ok": restored.integrity_ok,
                "size_bytes": restored.size_bytes,
            }


_fallback_locks = {}


def _fallback_lock(path: Path):
    import threading
    key = str(path.resolve(strict=False))
    return _fallback_locks.setdefault(key, threading.Lock())
