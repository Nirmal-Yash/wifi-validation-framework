#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.services.doctor import RunnerDoctor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only NetRegress Runner environment doctor")
    parser.add_argument("--database", type=Path, help="SQLite database path.")
    parser.add_argument("--check-dashboard", action="store_true", help="Check local API and frontend HTTP health.")
    parser.add_argument("--include-lab-tools", action="store_true", help="Check the protected-lab command prerequisites.")
    args = parser.parse_args(argv)
    report = RunnerDoctor(ROOT).run(
        database=args.database,
        check_dashboard=args.check_dashboard,
        include_lab_tools=args.include_lab_tools,
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
