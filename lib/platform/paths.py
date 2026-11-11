"""OS-aware application paths with legacy source-checkout compatibility."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from .detection import platform_family_for
from .contracts import PlatformFamily


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    root: Path
    packaged: bool
    family: PlatformFamily
    data_dir: Path
    config_dir: Path
    cache_dir: Path
    state_dir: Path
    logs_dir: Path
    runtime_dir: Path
    results_dir: Path
    captures_dir: Path
    backups_dir: Path
    database_path: Path

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "root": str(self.root),
            "packaged": self.packaged,
            "family": self.family.value,
            "data_dir": str(self.data_dir),
            "config_dir": str(self.config_dir),
            "cache_dir": str(self.cache_dir),
            "state_dir": str(self.state_dir),
            "logs_dir": str(self.logs_dir),
            "runtime_dir": str(self.runtime_dir),
            "results_dir": str(self.results_dir),
            "captures_dir": str(self.captures_dir),
            "backups_dir": str(self.backups_dir),
            "database_path": str(self.database_path),
        }


def _resolve(value: str | Path, *, root: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve(strict=False)


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_application_paths(
    project_root: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    system: str | None = None,
    home: str | Path | None = None,
    packaged: bool | None = None,
) -> ApplicationPaths:
    """Resolve application locations without creating directories.

    Source checkouts preserve the established .local and results/ defaults.
    Packaged builds use the host's conventional per-user locations. Existing
    NETREGRESS_LOCAL_DIR and database path variables remain supported.
    """
    root = Path(project_root or Path(__file__).resolve().parents[2]).expanduser().resolve(strict=False)
    if environ is None:
        # Use the same permission-checked .env loading policy as database
        # configuration; explicit process environment values remain dominant.
        from lib.repositories.database_config import _load_secure_dotenv
        _load_secure_dotenv(root)
    env = dict(os.environ if environ is None else environ)
    family = platform_family_for(system)
    home_dir = Path(home).expanduser() if home is not None else Path.home()
    is_packaged = _is_true(env.get("NETREGRESS_PACKAGED")) if packaged is None else bool(packaged)

    if not is_packaged:
        default_data = root / ".local"
        default_config = root / "configs"
        default_cache = default_data / "cache"
        default_state = default_data
        default_results = root / "results"
    elif family is PlatformFamily.LINUX:
        default_data = Path(env.get("XDG_DATA_HOME") or (home_dir / ".local" / "share")) / "netregress"
        default_config = Path(env.get("XDG_CONFIG_HOME") or (home_dir / ".config")) / "netregress"
        default_cache = Path(env.get("XDG_CACHE_HOME") or (home_dir / ".cache")) / "netregress"
        default_state = Path(env.get("XDG_STATE_HOME") or (home_dir / ".local" / "state")) / "netregress"
        default_results = default_data / "results"
    elif family is PlatformFamily.WINDOWS:
        local_app_data = Path(env.get("LOCALAPPDATA") or (home_dir / "AppData" / "Local"))
        roaming_app_data = Path(env.get("APPDATA") or (home_dir / "AppData" / "Roaming"))
        default_data = local_app_data / "NetRegress"
        default_config = roaming_app_data / "NetRegress"
        default_cache = default_data / "Cache"
        default_state = default_data / "State"
        default_results = default_data / "Results"
    elif family is PlatformFamily.MACOS:
        support = home_dir / "Library" / "Application Support" / "NetRegress"
        default_data = support
        default_config = home_dir / "Library" / "Preferences" / "NetRegress"
        default_cache = home_dir / "Library" / "Caches" / "NetRegress"
        default_state = home_dir / "Library" / "Logs" / "NetRegress"
        default_results = support / "Results"
    else:
        default_data = home_dir / ".netregress"
        default_config = default_data / "config"
        default_cache = default_data / "cache"
        default_state = default_data / "state"
        default_results = default_data / "results"

    # NETREGRESS_LOCAL_DIR is the established private-state override. The new
    # user-data spelling takes precedence when both are explicitly configured.
    data_value = env.get("NETREGRESS_USER_DATA_DIR") or env.get("NETREGRESS_LOCAL_DIR")
    data_dir = _resolve(data_value, root=root) if data_value else default_data.resolve(strict=False)
    if env.get("NETREGRESS_USER_DATA_DIR") and not env.get("NETREGRESS_RESULTS_DIR"):
        default_results = data_dir / ("Results" if family is PlatformFamily.WINDOWS else "results")
    config_dir = _resolve(env.get("NETREGRESS_CONFIG_DIR") or default_config, root=root)
    cache_dir = _resolve(env.get("NETREGRESS_CACHE_DIR") or (data_dir / "cache" if data_value else default_cache), root=root)
    state_dir = _resolve(env.get("NETREGRESS_STATE_DIR") or (data_dir if data_value or not is_packaged else default_state), root=root)
    logs_dir = _resolve(env.get("NETREGRESS_LOG_DIR") or (state_dir / "logs"), root=root)
    runtime_dir = _resolve(env.get("NETREGRESS_RUNTIME_DIR") or (state_dir / "runtime"), root=root)
    results_dir = _resolve(env.get("NETREGRESS_RESULTS_DIR") or default_results, root=root)
    captures_dir = results_dir / "captures"
    backups_dir = results_dir / "backups"

    database_variables = {"NETREGRESS_DATABASE_PATH", "TEST_DB_PATH", "DATABASE_URL"}
    has_database_override = any((env.get(key) or "").strip() for key in database_variables)
    if has_database_override:
        from lib.repositories.database_config import resolve_database_path
        database_path = resolve_database_path(
            environ={key: env[key] for key in database_variables if key in env},
            project_root=root,
        )
    elif environ is None:
        # Keep .env loading and all existing resolver precedence for established
        # checkouts. Only remap its untouched default when RESULTS_DIR is changed.
        from lib.repositories.database_config import resolve_database_path
        resolved = resolve_database_path(project_root=root)
        legacy_default = (root / "results" / "test_results.db").resolve(strict=False)
        database_path = (
            results_dir / "test_results.db"
            if resolved.resolve(strict=False) == legacy_default
            else resolved
        )
    else:
        database_path = results_dir / "test_results.db"

    return ApplicationPaths(
        root=root,
        packaged=is_packaged,
        family=family,
        data_dir=data_dir.resolve(strict=False),
        config_dir=config_dir,
        cache_dir=cache_dir,
        state_dir=state_dir,
        logs_dir=logs_dir,
        runtime_dir=runtime_dir,
        results_dir=results_dir,
        captures_dir=captures_dir,
        backups_dir=backups_dir,
        database_path=Path(database_path).expanduser().resolve(strict=False),
    )
