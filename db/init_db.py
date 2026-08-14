#!/usr/bin/env python3
"""Create and validate the NetForge SQLite database.

This module is intentionally dependency-free so database bootstrap works before
any optional networking packages are installed.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "db" / "results.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize(path: Path = DB_PATH) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect(path) as conn:
        conn.executescript(schema)
        conn.commit()


def validate(path: Path = DB_PATH) -> list[str]:
    with connect(path) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        required = {
            "firmware_metadata", "test_logs", "topologies", "topology_nodes",
            "topology_links", "executions", "test_results", "evidence", "audit_events"
        }
        missing = sorted(required - set(tables))
        if missing:
            raise RuntimeError(f"Database schema incomplete; missing tables: {', '.join(missing)}")
        return tables


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()
    path = Path(args.db).resolve()
    initialize(path)
    tables = validate(path)
    print(f"Database ready: {path}")
    print(f"Tables: {', '.join(tables)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
