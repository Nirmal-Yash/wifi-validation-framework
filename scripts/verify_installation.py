#!/usr/bin/env python3
"""Verify the NetForge baseline without requiring privileged networking."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

REQUIRED = [
    "README.md", "requirements.txt", "db/schema.sql", "db/init_db.py",
    "dashboard/app.py", "dashboard/db.py", "dashboard/templates/topology.html",
    "config/devices.yaml", "tests/conftest.py"
]


def main() -> int:
    failures = []
    for rel in REQUIRED:
        if not (ROOT / rel).exists():
            failures.append(f"missing: {rel}")
    if failures:
        print("STRUCTURE FAILED")
        print("\n".join(failures))
        return 1

    try:
        from db.init_db import initialize, validate
        initialize(ROOT / "db/results.db")
        validate(ROOT / "db/results.db")
        print("database: PASS")
    except Exception as exc:
        print(f"database: FAIL: {exc}")
        return 1

    for module in ("flask", "yaml", "pytest"):
        try:
            importlib.import_module(module)
            print(f"dependency {module}: PASS")
        except ImportError as exc:
            print(f"dependency {module}: FAIL ({exc})")
            return 1

    try:
        from dashboard.app import app
        with app.test_client() as client:
            response = client.get("/health")
            if response.status_code != 200:
                print(f"dashboard health: FAIL ({response.status_code})")
                return 1
            print("dashboard health: PASS")
            response = client.get("/api/topology_data")
            if response.status_code != 200:
                print(f"topology API: FAIL ({response.status_code})")
                return 1
            payload = response.get_json()
            if not payload or payload.get("success") is not True:
                print("topology API: FAIL (invalid response envelope)")
                return 1
            print("topology API: PASS")
    except Exception as exc:
        print(f"dashboard: FAIL: {exc}")
        return 1

    print("\nNETFORGE INSTALLATION VERIFICATION: PASS")
    print("Privileged netns/hwsim tests are not executed by this verifier.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
