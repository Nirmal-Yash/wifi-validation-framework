"""Secure persistent paths and secrets for the packaged desktop backend."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import stat
from typing import Mapping

from .adapters import LinuxPlatformAdapter
from .contracts import PlatformCapabilityError
from .paths import ApplicationPaths, resolve_application_paths


@dataclass(frozen=True, slots=True)
class DesktopRuntime:
    paths: ApplicationPaths
    session_secret_file: Path


def _ensure_session_secret(path: Path) -> str:
    flags = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, os.O_RDONLY | flags)
    except FileNotFoundError:
        secret = secrets.token_hex(32)
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | flags,
                0o600,
            )
        except FileExistsError:
            return _ensure_session_secret(path)
        try:
            payload = secret.encode("ascii")
            written = os.write(descriptor, payload)
            if written != len(payload):
                raise OSError("session secret write was incomplete")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return secret

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("desktop session secret must be a regular file")
        if metadata.st_uid != os.getuid():
            raise RuntimeError("desktop session secret must be owned by the current user")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RuntimeError("desktop session secret permissions must be 0600")
        payload = os.read(descriptor, 256)
    finally:
        os.close(descriptor)
    try:
        secret = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("desktop session secret is not valid ASCII") from exc
    if len(secret) != 64 or any(character not in "0123456789abcdef" for character in secret):
        raise RuntimeError("desktop session secret file is invalid")
    return secret


def _reject_symlinked_path(path: str | Path, *, label: str) -> None:
    candidate = Path(path).expanduser().absolute()
    for component in (candidate, *candidate.parents):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise PlatformCapabilityError(
                f"{label} path must not contain a symlink"
            )


def prepare_desktop_runtime(
    project_root: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
    port: int | None = None,
) -> DesktopRuntime:
    """Prepare private user-data directories and the persistent Flask session key.

    This entry point is intentionally Linux-only for the first packaged release.
    Windows has its own platform and credential-store adapters, but the Windows
    desktop product is a separate qualification target.
    """
    env = dict(os.environ if environ is None else environ)
    # Validate caller-supplied paths before resolve_application_paths() applies
    # Path.resolve(), which intentionally canonicalizes symlinks for normal
    # source-checkout resolution.
    for variable, label in (
        ("NETREGRESS_USER_DATA_DIR", "user data"),
        ("NETREGRESS_LOCAL_DIR", "local state"),
        ("NETREGRESS_CONFIG_DIR", "configuration"),
        ("NETREGRESS_CACHE_DIR", "cache"),
        ("NETREGRESS_STATE_DIR", "state"),
        ("NETREGRESS_LOG_DIR", "logs"),
        ("NETREGRESS_RUNTIME_DIR", "runtime"),
        ("NETREGRESS_RESULTS_DIR", "results"),
    ):
        value = str(env.get(variable) or "").strip()
        if value:
            _reject_symlinked_path(value, label=label)
    env["NETREGRESS_PACKAGED"] = "1"
    env["NETREGRESS_AUTH_REQUIRED"] = "1"
    env["NETREGRESS_AUTH_USERS_JSON"] = ""
    env.setdefault("NETREGRESS_SESSION_COOKIE_SECURE", "1")
    env.setdefault("NETREGRESS_SESSION_COOKIE_SAMESITE", "None")
    if port is not None:
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise ValueError("desktop backend port must be between 1024 and 65535")
        env["NETREGRESS_PORT"] = str(port)

    paths = resolve_application_paths(
        project_root,
        environ=env,
        system="Linux",
        home=home,
        packaged=True,
    )
    adapter = LinuxPlatformAdapter()
    for directory in (
        paths.data_dir,
        paths.config_dir,
        paths.cache_dir,
        paths.state_dir,
        paths.logs_dir,
        paths.runtime_dir,
        paths.results_dir,
        paths.captures_dir,
        paths.backups_dir,
        paths.results_dir / "processes",
    ):
        adapter.ensure_private_directory(directory)

    session_secret_file = paths.state_dir / "session-secret"
    session_secret = _ensure_session_secret(session_secret_file)

    env_updates = {
        "NETREGRESS_PACKAGED": "1",
        "NETREGRESS_AUTH_REQUIRED": "1",
        "NETREGRESS_AUTH_USERS_JSON": "",
        "NETREGRESS_USER_DATA_DIR": str(paths.data_dir),
        "NETREGRESS_LOCAL_DIR": str(paths.data_dir),
        "NETREGRESS_CONFIG_DIR": str(paths.config_dir),
        "NETREGRESS_CACHE_DIR": str(paths.cache_dir),
        "NETREGRESS_STATE_DIR": str(paths.state_dir),
        "NETREGRESS_LOG_DIR": str(paths.logs_dir),
        "NETREGRESS_RUNTIME_DIR": str(paths.runtime_dir),
        "NETREGRESS_RESULTS_DIR": str(paths.results_dir),
        "NETREGRESS_PROCESS_DIR": str(paths.results_dir / "processes"),
        "NETREGRESS_DATABASE_PATH": str(paths.database_path),
        "TEST_DB_PATH": str(paths.database_path),
        "NETREGRESS_SESSION_SECRET": session_secret,
        "NETREGRESS_SESSION_COOKIE_SECURE": env["NETREGRESS_SESSION_COOKIE_SECURE"],
        "NETREGRESS_SESSION_COOKIE_SAMESITE": env["NETREGRESS_SESSION_COOKIE_SAMESITE"],
    }
    if "NETREGRESS_PORT" in env:
        env_updates["NETREGRESS_PORT"] = env["NETREGRESS_PORT"]
    if environ is None:
        os.environ.update(env_updates)
    else:
        # A supplied mapping is a test seam. The caller owns applying returned
        # values to its process environment.
        if hasattr(environ, "update"):
            environ.update(env_updates)  # type: ignore[attr-defined]
    return DesktopRuntime(paths=paths, session_secret_file=session_secret_file)
