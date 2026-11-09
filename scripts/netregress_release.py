#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.services.doctor import RunnerDoctor
from lib.services.release_manifest import ReleaseManifestService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NetRegress release metadata and readiness checks")
    parser.add_argument("mode", choices=("verify", "manifest", "doctor", "verify-manifest"))
    parser.add_argument("--manifest", default="results/release-manifest.json")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--core-tests", action="store_true")
    parser.add_argument("--check-dashboard", action="store_true")
    parser.add_argument("--include-lab-tools", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "doctor":
        report = RunnerDoctor(ROOT).run(
            database=args.database,
            check_dashboard=args.check_dashboard,
            include_lab_tools=args.include_lab_tools,
        )
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        return 0 if report.ready else 1

    service = ReleaseManifestService(ROOT)
    if args.mode == "verify-manifest":
        result = service.verify_manifest(args.manifest)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["verified"] else 1

    audit = service.audit()
    payload = service.manifest(audit=audit)
    if args.mode == "manifest":
        destination = service.write_manifest(args.manifest)
        print(json.dumps({
            "manifest": str(destination),
            "release_ready": payload["release_ready"],
            "production_reproducible": payload["production_reproducible"],
            "dependency_status": payload["dependencies"]["status"],
        }, indent=2, sort_keys=True))
        return 0 if payload["release_ready"] else 1

    if args.core_tests:
        result = subprocess.run(
            [sys.executable, "scripts/ci_release_gate.py"],
            cwd=ROOT,
            check=False,
        )
        if result.returncode:
            return result.returncode

    destination = service.write_manifest(args.manifest)
    print(json.dumps({
        "manifest": str(destination),
        "release_ready": payload["release_ready"],
        "production_reproducible": payload["production_reproducible"],
        "dependency_status": payload["dependencies"]["status"],
        "branch": payload["source"]["branch"],
        "commit": payload["source"]["commit"],
        "tree": payload["source"]["tree"],
        "tracked_file_count": payload["tracked_file_count"],
    }, indent=2, sort_keys=True))
    return 0 if payload["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
