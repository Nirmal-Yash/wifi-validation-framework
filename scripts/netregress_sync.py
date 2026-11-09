#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.repositories import SQLiteDatabase, SQLiteSyncQueueRepository
from lib.services import HttpSyncTransport, RunnerSyncService


def _queue_status(database: SQLiteDatabase, *, runner_id: str) -> int:
    if not database.path.is_file():
        payload = {
            "mode": "status",
            "status": "NOT_INITIALIZED",
            "runner_id": runner_id,
            "database_path": str(database.path),
            "queue": None,
            "message": "Runner database does not exist; status inspection made no changes.",
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    try:
        summary = SQLiteSyncQueueRepository(database).summary()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            payload = {
                "mode": "status",
                "status": "SCHEMA_UNAVAILABLE",
                "runner_id": runner_id,
                "database_path": str(database.path),
                "queue": None,
                "message": "Sync queue schema is unavailable; run the database status/upgrade command explicitly.",
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 2
        raise

    pending = summary["QUEUED"] + summary["IN_FLIGHT"] + summary["FAILED"]
    payload = {
        "mode": "status",
        "status": "READY",
        "runner_id": runner_id,
        "database_path": str(database.path),
        "queue": summary,
        "pending_delivery": pending,
        "blocked_attention": summary["BLOCKED"],
        "message": "Local queue inspected read-only; no network request or schema migration was attempted.",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or synchronize locally queued NetRegress Runner envelopes"
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--url", default=os.getenv("NETREGRESS_SYNC_URL"))
    parser.add_argument(
        "--runner-id",
        default=os.getenv("NETREGRESS_RUNNER_ID") or os.getenv("HOSTNAME") or "local-runner",
    )
    parser.add_argument("--token", default=os.getenv("NETREGRESS_SYNC_TOKEN"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--status",
        action="store_true",
        help="Read queue counts locally without contacting Cloud or running migrations.",
    )
    args = parser.parse_args(argv)

    if args.status:
        return _queue_status(SQLiteDatabase(args.db), runner_id=args.runner_id)

    if not args.url:
        parser.error("--url or NETREGRESS_SYNC_URL is required unless --status is used")
    if args.limit < 1:
        parser.error("--limit must be positive")

    database = SQLiteDatabase(args.db)
    service = RunnerSyncService.from_sqlite(database, runner_id=args.runner_id)
    summary = service.sync_pending(
        HttpSyncTransport(args.url, bearer_token=args.token),
        limit=args.limit,
    )
    print(json.dumps(summary, sort_keys=True))
    return 1 if summary["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
