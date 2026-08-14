from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "db" / "results.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"


def connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def ensure_schema() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with connection() as conn:
        conn.executescript(schema)
        conn.commit()
