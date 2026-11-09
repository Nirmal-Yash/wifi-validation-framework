#!/usr/bin/env python3
"""Compatibility wrapper for the retired WiFi Framework self-check script.

The canonical source/release gate is scripts/netregress_release.py. This file
keeps the historical entry point but does not write ad-hoc reports or mutate
the operational database.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    print(
        "verify_system.py is a compatibility entry point; "
        "delegating to the canonical NetRegress release verification."
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "netregress_release.py"),
            "verify",
            "--core-tests",
        ],
        cwd=ROOT,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
