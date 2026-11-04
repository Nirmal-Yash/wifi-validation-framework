#!/usr/bin/env python3
"""Import historical legacy SQLite rows into the canonical Runner database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.repositories import SQLiteDatabase, resolve_database_path
from lib.services.legacy_migration import LegacyDatabaseMigrationService


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Idempotently import legacy test_runs/baselines into canonical SQLite repositories."
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Legacy SQLite source. Omit to migrate legacy tables in the target database in place.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        help="Canonical target database (defaults to the Runner database resolver).",
    )
    parser.add_argument(
        "--source-identity",
        help="Stable logical identity for this source; defaults to its resolved path.",
    )
    args = parser.parse_args(argv)

    target_path = args.target or resolve_database_path(project_root=ROOT)
    target = SQLiteDatabase(target_path)
    source_path = args.source or target.path
    service = LegacyDatabaseMigrationService(
        target,
        source_path,
        source_identity=args.source_identity,
    )
    try:
        summary = service.migrate()
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": f"{type(exc).__name__}: {exc}"},
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if summary["failed"] or summary["invalid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
