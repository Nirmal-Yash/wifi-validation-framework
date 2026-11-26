#!/usr/bin/env python3
"""Interactively reset a persistent local NetRegress Global Owner password."""

from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_environment() -> None:
    env_file = ROOT / ".env"
    if env_file.is_symlink():
        raise PermissionError(".env must not be a symlink")
    if env_file.is_file():
        if stat.S_IMODE(env_file.stat().st_mode) & 0o077:
            raise PermissionError(".env must be owner-readable only (chmod 600)")
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)


def _load_legacy_accounts(local_dir: Path):
    auth_file = local_dir / "netregress-auth.json"
    if auth_file.is_symlink():
        raise PermissionError("legacy authentication file must not be a symlink")
    if auth_file.is_file():
        metadata = auth_file.stat()
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise PermissionError("legacy authentication file must be owned by this user with mode 0600")
        if not os.getenv("NETREGRESS_AUTH_USERS_JSON", "").strip():
            os.environ["NETREGRESS_AUTH_USERS_JSON"] = auth_file.read_text(encoding="utf-8")
    from lib.security import AuthManager
    return AuthManager.from_env().configured_users


def _archive_legacy_accounts(local_dir: Path) -> None:
    source = local_dir / "netregress-auth.json"
    if not source.is_file() or source.is_symlink():
        return
    target = source.with_name(source.name + ".migrated")
    suffix = 1
    while target.exists():
        target = source.with_name(source.name + f".migrated-{suffix}")
        suffix += 1
    os.replace(source, target)
    os.chmod(target, 0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reset a Global Owner password in the persistent NetRegress identity database."
    )
    parser.add_argument("--username", help="Global Owner username; omitted when exactly one active Owner exists.")
    args = parser.parse_args(argv)

    try:
        _load_environment()
        local_dir = Path(
            os.getenv("NETREGRESS_LOCAL_DIR") or (ROOT / ".local")
        ).expanduser()
        if not local_dir.is_absolute():
            local_dir = ROOT / local_dir
        if local_dir.is_symlink():
            raise PermissionError("local-state directory must not be a symlink")

        from lib.repositories import SQLiteDatabase, resolve_database_path
        from lib.repositories.database_migrations import DatabaseMigrationManager
        from lib.services.identity import IdentityStore

        database_path = resolve_database_path(project_root=ROOT)
        migration = DatabaseMigrationManager(database_path, project_root=ROOT).check()
        if not migration.is_up_to_date:
            raise RuntimeError(
                "database schema is not at the current Alembic head; run "
                "'python scripts/netregress_install.py' before resetting credentials"
            )

        identity = IdentityStore(SQLiteDatabase(database_path))
        legacy_users = _load_legacy_accounts(local_dir)
        identity.import_legacy_auth_users(
            legacy_users, actor="legacy-auth-config-migration",
        )

        active_owners = [
            user for user in identity.list_users()
            if user.get("status") == "ACTIVE" and user.get("global_role") == "OWNER"
        ]
        if args.username:
            selected = next(
                (user for user in active_owners if user["username"].casefold() == args.username.casefold()),
                None,
            )
            if selected is None:
                raise RuntimeError("the requested account is not an active Global Owner")
        elif len(active_owners) == 1:
            selected = active_owners[0]
        elif not active_owners:
            raise RuntimeError(
                "no active Global Owner exists; start the dashboard and complete first-run Owner setup"
            )
        else:
            choices = ", ".join(sorted(user["username"] for user in active_owners))
            raise RuntimeError(
                "multiple active Global Owners exist; rerun with --username. Available: " + choices
            )

        password = getpass("New Global Owner password (at least 12 characters): ")
        confirmation = getpass("Confirm new password: ")
        if password != confirmation:
            raise ValueError("password confirmation does not match")
        result = identity.reset_owner_password(
            selected["username"], password, actor="local-console-reset",
        )
        _archive_legacy_accounts(local_dir)
        print(
            "Global Owner password reset in IdentityStore. "
            f"Account: {selected['username']}. "
            f"Revoked sessions: {result['revoked_sessions']}."
        )
        print("The local session-signing key was preserved; revoked database sessions cannot be reused.")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"OWNER RESET FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
