#!/usr/bin/env python3
"""Inspect, upgrade, back up and restore the canonical Runner SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.repositories import resolve_database_path
from lib.repositories.database_migrations import (
    DatabaseMigrationError,
    DatabaseMigrationManager,
)


def _json(payload) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Alembic-owned NetRegress SQLite schema governance and recovery."
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite database path; defaults to the canonical Runner path resolver.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show current Alembic revision and schema state.")
    subparsers.add_parser("check", help="Fail if migration or physical schema drift exists.")
    subparsers.add_parser("upgrade", help="Back up, upgrade to Alembic head and verify drift.")
    backup_parser = subparsers.add_parser("backup", help="Create a consistent verified SQLite backup.")
    backup_parser.add_argument("--output", type=Path, help="Backup destination (must not exist).")
    restore_parser = subparsers.add_parser("restore", help="Restore a verified SQLite backup.")
    restore_parser.add_argument("--backup", type=Path, required=True, help="Backup SQLite file.")
    restore_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required explicit confirmation; stop all Runner processes first.",
    )
    args = parser.parse_args(argv)

    try:
        database = args.database or resolve_database_path(project_root=ROOT)
        manager = DatabaseMigrationManager(database, project_root=ROOT)

        if args.command == "status":
            report = manager.check()
            _json(report.as_dict())
            return 0 if report.is_up_to_date else 1

        if args.command == "check":
            report = manager.check()
            _json(report.as_dict())
            return 0 if report.is_up_to_date else 1

        if args.command == "upgrade":
            report = manager.upgrade()
            _json(report.as_dict())
            return 0

        if args.command == "backup":
            result = manager.backup(args.output)
            _json(
                {
                    "source": str(result.source),
                    "destination": str(result.destination),
                    "integrity_ok": result.integrity_ok,
                    "size_bytes": result.size_bytes,
                    "sha256": result.sha256,
                }
            )
            return 0 if result.integrity_ok else 1

        if args.command == "restore":
            if not args.confirm:
                parser.error("restore requires --confirm after stopping all Runner processes")
            result = manager.restore(args.backup)
            _json(result)
            return 0 if result["integrity_ok"] else 1

    except (DatabaseMigrationError, OSError, ValueError, sqlite3.Error) as exc:
        print(
            json.dumps(
                {"status": "failed", "error": f"{type(exc).__name__}: {exc}"},
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
