#!/usr/bin/env python3
"""Packaged NetRegress backend entry point and frozen child-process dispatcher."""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys


ROOT = Path(
    getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])
).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _dispatch_frozen_child(arguments: list[str]) -> int | None:
    """Route Runner subprocess commands through the PyInstaller executable."""
    if not getattr(sys, "frozen", False) or not arguments:
        return None
    # Runner children are launched by sys.executable from the PyInstaller
    # sidecar. Keep their cwd rooted in the embedded, read-only application
    # resources rather than inheriting a desktop/user-data working directory.
    os.chdir(ROOT)
    if len(arguments) >= 2 and arguments[0] == "-m" and arguments[1] == "pytest":
        import pytest

        sys.argv = [str(Path(sys.executable).name), *arguments[2:]]
        return int(pytest.main(arguments[2:]))
    candidate = Path(arguments[0])
    if candidate.name == "netregress_pipeline_worker.py":
        script = ROOT / "scripts" / candidate.name
        if not script.is_file():
            raise FileNotFoundError("packaged pipeline worker is missing")
        sys.argv = [str(script), *arguments[1:]]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    return None


def _check_desktop_runtime() -> int:
    """Verify dynamically loaded stdlib and migration imports in the frozen app."""
    import importlib

    required_modules = (
        "logging.config",
        "alembic",
        "alembic.command",
        "alembic.config",
        "alembic.script",
        "sqlalchemy",
    )
    for module_name in required_modules:
        importlib.import_module(module_name)
    print("Packaged desktop runtime imports validated: " + ", ".join(required_modules))
    return 0


def main() -> int:
    if sys.argv[1:] == ["--check-desktop-runtime"]:
        return _check_desktop_runtime()

    child_result = _dispatch_frozen_child(sys.argv[1:])
    if child_result is not None:
        return child_result

    os.chdir(ROOT)
    from lib.platform.desktop_runtime import prepare_desktop_runtime
    from lib.repositories.database_migrations import DatabaseMigrationManager

    runtime = prepare_desktop_runtime(ROOT)
    DatabaseMigrationManager(
        runtime.paths.database_path,
        project_root=ROOT,
    ).upgrade()

    # Import only after private paths, session entropy and schema are ready.
    from dashboard.app import RUNNER_HOST, RUNNER_PORT, app

    app.run(
        host=RUNNER_HOST,
        port=RUNNER_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
