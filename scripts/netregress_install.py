#!/usr/bin/env python3
"""Initialize a standalone NetRegress checkout and its canonical SQLite store."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.repositories import resolve_database_path
from lib.repositories.database_migrations import DatabaseMigrationManager
from lib.services.doctor import RunnerDoctor


SOURCE_REQUIREMENTS = (
    "requirements.txt",
    "alembic.ini",
    "alembic",
    "configs",
    "dashboard",
    "frontend",
    "lib",
    "scripts",
)


def prepare_runtime_directories(
    root: str | Path,
    *,
    local_dir: str | Path | None = None,
    check_only: bool = False,
) -> dict[str, object]:
    repository = Path(root).expanduser().resolve()
    missing_sources = [
        relative for relative in SOURCE_REQUIREMENTS
        if not (repository / relative).exists()
    ]
    if missing_sources:
        raise RuntimeError("not a NetRegress checkout; missing: " + ", ".join(missing_sources))

    configured_local = local_dir or os.getenv("NETREGRESS_LOCAL_DIR")
    local_candidate = (
        Path(configured_local).expanduser()
        if configured_local
        else repository / ".local"
    )
    if not local_candidate.is_absolute():
        local_candidate = repository / local_candidate
    if local_candidate.is_symlink():
        raise RuntimeError("local-state directory must not be a symlink")
    local = local_candidate.resolve()

    results = repository / "results"
    if results.is_symlink():
        raise RuntimeError("results directory must not be a symlink")
    paths = {
        "results": results,
        "reports": results / "reports",
        "captures": results / "captures",
        "backups": results / "backups",
        "diagnostics": results / "diagnostics",
        "certification_evidence": results / "certification-evidence",
        "local_state": local,
        "local_logs": local / "logs",
    }
    for name, path in paths.items():
        if path.exists() and path.is_symlink():
            raise RuntimeError(f"runtime directory must not be a symlink: {name}")
        if name not in {"local_state", "local_logs"} and path.exists():
            if not path.resolve().is_relative_to(results.resolve()):
                raise RuntimeError(f"runtime path escapes results directory: {name}")

    missing = [name for name, path in paths.items() if not path.is_dir()]
    if check_only:
        return {
            "created": [],
            "existing": [name for name in paths if name not in missing],
            "missing": missing,
            "paths": {name: str(path) for name, path in paths.items()},
        }

    for name in ("local_state", "local_logs"):
        path = paths[name]
        if path.is_dir() and (stat.S_IMODE(path.stat().st_mode) & 0o077):
            raise PermissionError(
                f"{path} already exists with unsafe permissions; "
                "restrict it to owner-only access before installation"
            )

    created: list[str] = []
    for name, path in paths.items():
        existed = path.is_dir()
        path.mkdir(parents=True, exist_ok=True, mode=0o700 if name.startswith("local") else 0o750)
        if not existed:
            created.append(name)
    for name in ("local_state", "local_logs"):
        if name in created:
            os.chmod(paths[name], stat.S_IRWXU)
    return {
        "created": created,
        "existing": [name for name in paths if name not in created],
        "missing": [],
        "paths": {name: str(path) for name, path in paths.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare NetRegress standalone runtime directories and SQLite schema."
    )
    parser.add_argument("--database", type=Path, help="Explicit SQLite database path.")
    parser.add_argument("--local-dir", type=Path, help="Private local-state directory (defaults to .local).")
    parser.add_argument("--skip-database", action="store_true", help="Prepare paths without creating or upgrading SQLite.")
    parser.add_argument("--check-only", action="store_true", help="Read-only preflight; do not create directories or migrate.")
    parser.add_argument("--check-dashboard", action="store_true", help="Check the running local API and frontend.")
    parser.add_argument("--include-lab-tools", action="store_true", help="Require protected-lab CLI tools.")
    args = parser.parse_args(argv)

    try:
        env_file = ROOT / ".env"
        if env_file.is_symlink():
            raise PermissionError(".env must be a regular file, not a symlink")
        if env_file.is_file():
            if stat.S_IMODE(env_file.stat().st_mode) & 0o077:
                raise PermissionError(".env must be owner-readable only before installation")
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=env_file, override=False)

        directories = prepare_runtime_directories(
            ROOT,
            local_dir=args.local_dir,
            check_only=args.check_only,
        )
        if directories["missing"] and args.check_only:
            raise RuntimeError("runtime directories are missing: " + ", ".join(directories["missing"]))

        database_path = None
        migration_payload: dict[str, object] | None = None
        if not args.skip_database:
            database_path = resolve_database_path(args.database, project_root=ROOT)
            manager = DatabaseMigrationManager(database_path, project_root=ROOT)
            if args.check_only:
                status = manager.check()
                migration_payload = status.as_dict()
                if not status.is_up_to_date:
                    raise RuntimeError("database schema is not at the current Alembic head")
            else:
                status = manager.upgrade()
                migration_payload = status.as_dict()

        doctor = RunnerDoctor(ROOT).run(
            database=database_path,
            check_dashboard=args.check_dashboard,
            include_lab_tools=args.include_lab_tools,
        )
        payload = {
            "status": "PASS" if doctor.ready else "FAIL",
            "directories": directories,
            "database": migration_payload,
            "doctor": doctor.as_dict(),
            "note": "Warnings and NOT_CHECKED results remain visible; they are not certification evidence.",
        }
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0 if doctor.ready else 1
    except Exception as exc:
        print(
            json.dumps(
                {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"},
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
