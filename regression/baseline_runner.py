"""Promote a validated canonical Run as the firmware regression baseline."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.repositories import SQLiteDatabase
from lib.services import RunService


def run_baseline(firmware_version="v1.0", run_tests=False, run_id=None):
    root = Path(__file__).resolve().parent.parent
    database = SQLiteDatabase()
    database.initialize()
    if run_tests:
        print(f"Running full test suite for baseline {firmware_version}...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/",
                "-v",
                f"--firmware-version={firmware_version}",
            ],
            cwd=root,
            check=True,
        )

    if run_id is None:
        with database.connection() as connection:
            row = connection.execute(
                """SELECT run_id FROM runs
                   WHERE firmware_version = ?
                     AND lifecycle = 'COMPLETED'
                     AND outcome IN ('VALIDATED', 'VALIDATED_WITH_WARNINGS')
                     AND environment_health = 'HEALTHY'
                     AND provenance = 'NATIVE'
                   ORDER BY completed_at DESC, created_at DESC
                   LIMIT 1""",
                (firmware_version,),
            ).fetchone()
        if row is None:
            raise RuntimeError(
                f"No eligible validated Run exists for {firmware_version}; "
                "legacy compatibility records cannot be promoted."
            )
        run_id = row["run_id"]

    with database.connection() as connection:
        candidate = connection.execute(
            """SELECT firmware_version, lifecycle, outcome,
                      environment_health, provenance
               FROM runs WHERE run_id = ?""",
            (run_id,),
        ).fetchone()
    if candidate is None:
        raise RuntimeError(f"Run does not exist: {run_id}")
    if candidate["firmware_version"] != firmware_version:
        raise RuntimeError(
            f"Run {run_id} belongs to firmware {candidate['firmware_version']}, "
            f"not requested firmware {firmware_version}."
        )
    if candidate["provenance"] != "NATIVE":
        raise RuntimeError("Only native Runs can be promoted; imported history is read-only.")
    if (
        candidate["lifecycle"] != "COMPLETED"
        or candidate["environment_health"] != "HEALTHY"
        or candidate["outcome"] not in {"VALIDATED", "VALIDATED_WITH_WARNINGS"}
    ):
        raise RuntimeError("Run is not a completed, healthy, validated baseline candidate.")

    service = RunService.from_sqlite(database)
    promoted = service.promote_baseline(
        run_id,
        name=f"firmware/{firmware_version}",
        promoted_by=os.getenv("NETREGRESS_BASELINE_ACTOR", "local-operator"),
        firmware_major_scope=firmware_version.split(".")[0],
    )
    print(
        f"Promoted validated Run {run_id} as baseline {promoted.baseline_id} "
        f"for firmware {firmware_version}."
    )
    print("Only native Runs with healthy lab state and complete evidence are eligible.")
    return promoted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Promote a validated Run as firmware baseline")
    parser.add_argument("--version", default="v1.0", help="Firmware version tag")
    parser.add_argument("--run-id", default=None, help="Explicit eligible Run ID to promote")
    parser.add_argument("--run-tests", action="store_true", help="Run pytest before selecting the latest eligible Run")
    args = parser.parse_args()
    run_baseline(args.version, args.run_tests, args.run_id)
