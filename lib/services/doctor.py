from __future__ import annotations

from dataclasses import dataclass
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
from urllib.error import URLError
from urllib.request import urlopen

from lib.repositories.database_config import (
    DatabaseConfigurationError,
    resolve_database_path,
)
from lib.repositories.database_migrations import DatabaseMigrationManager


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    check_id: str
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]
    ready: bool
    summary: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "summary": self.summary,
            "checks": [
                {
                    "check_id": check.check_id,
                    "status": check.status,
                    "message": check.message,
                }
                for check in self.checks
            ],
        }


class RunnerDoctor:
    """Read-only standalone Runner diagnostics.

    PASS means the check was executed and its condition was verified.
    WARNING is a known non-blocking condition, FAIL is a required unmet
    condition, and NOT_CHECKED means the operator did not request that check.
    """

    REQUIRED_MODULES = (
        ("Flask", "flask"),
        ("Jinja2", "jinja2"),
        ("SQLAlchemy", "sqlalchemy"),
        ("Alembic", "alembic"),
        ("PyYAML", "yaml"),
        ("requests", "requests"),
        ("python-dotenv", "dotenv"),
        ("Paramiko", "paramiko"),
        ("Netmiko", "netmiko"),
        ("pytest", "pytest"),
        ("Scapy", "scapy"),
    )
    OPTIONAL_MODULES = (
        ("PyShark", "pyshark"),
        ("pytest-html", "pytest_html"),
    )
    REQUIRED_DIRECTORIES = (
        "configs",
        "lib",
        "dashboard",
        "scripts",
        "alembic",
        "frontend",
    )
    RUNTIME_DIRECTORIES = (
        "results",
        "results/reports",
        "results/captures",
        "results/backups",
        "results/diagnostics",
        "results/certification-evidence",
    )
    LAB_TOOLS = ("ip", "iw", "tcpdump", "ssh", "iperf3", "tshark")

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    @staticmethod
    def _node_supported(version: str) -> bool:
        parts = version.split(".")
        try:
            major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2].split("-")[0]))
        except (ValueError, IndexError):
            return False
        return (
            (major == 22 and (minor > 22 or (minor == 22 and patch >= 2)))
            or (major == 24 and minor >= 15)
            or major >= 26
        )

    @staticmethod
    def _is_true(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def run(
        self,
        *,
        database: str | Path | None = None,
        check_dashboard: bool = False,
        include_lab_tools: bool = False,
    ) -> DoctorReport:
        checks: list[DoctorCheck] = []

        def add(check_id: str, status: str, message: str) -> None:
            checks.append(DoctorCheck(check_id, status, message))

        add(
            "python",
            "PASS" if sys.version_info >= (3, 11) else "FAIL",
            f"Python {sys.version.split()[0]}",
        )
        add(
            "path:repository",
            "PASS" if self.root.is_dir() else "FAIL",
            str(self.root),
        )

        for distribution, module in self.REQUIRED_MODULES:
            try:
                available = importlib.util.find_spec(module) is not None
            except (ImportError, ValueError):
                available = False
            if not available:
                add(f"dependency:{distribution}", "FAIL", "required Python dependency is unavailable")
                continue
            try:
                version = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                version = "installed"
            add(f"dependency:{distribution}", "PASS", f"available ({version})")

        for distribution, module in self.OPTIONAL_MODULES:
            try:
                available = importlib.util.find_spec(module) is not None
            except (ImportError, ValueError):
                available = False
            add(
                f"optional:{distribution}",
                "PASS" if available else "WARNING",
                "available" if available else "optional dependency is not installed",
            )

        for relative in self.REQUIRED_DIRECTORIES:
            path = self.root / relative
            add(
                f"path:{relative}",
                "PASS" if path.is_dir() else "FAIL",
                "directory present" if path.is_dir() else "required application directory is missing",
            )

        tests_dir = self.root / "tests"
        add(
            "path:tests",
            "PASS" if tests_dir.is_dir() else "NOT_CHECKED",
            "test suite present" if tests_dir.is_dir() else "test sources are not required by a runtime-only deployment",
        )
        add(
            "tool:git",
            "PASS" if shutil.which("git") else "WARNING",
            "available" if shutil.which("git") else "Git is unavailable; source-manifest operations need Git",
        )
        add(
            "tool:pytest",
            "PASS" if shutil.which("pytest") else "WARNING",
            "available" if shutil.which("pytest") else "pytest command is unavailable on PATH",
        )

        env_file = self.root / ".env"
        env_file_safe = False
        if env_file.is_symlink():
            add("secrets:file_permissions", "FAIL", ".env must be a regular file, not a symlink")
            add("configuration:dotenv", "NOT_CHECKED", ".env symlink was not loaded")
        elif env_file.is_file():
            mode = stat.S_IMODE(env_file.stat().st_mode)
            env_file_safe = not (mode & 0o077)
            add(
                "secrets:file_permissions",
                "PASS" if env_file_safe else "FAIL",
                ".env permissions are owner-only" if env_file_safe else ".env is accessible by group or other users; restrict it to owner-only",
            )
            if env_file_safe:
                try:
                    from dotenv import load_dotenv
                    load_dotenv(dotenv_path=env_file, override=False)
                    add("configuration:dotenv", "PASS", ".env was loaded without overriding process environment")
                except Exception as exc:
                    add("configuration:dotenv", "FAIL", f".env could not be parsed: {type(exc).__name__}")
            else:
                add("configuration:dotenv", "NOT_CHECKED", ".env permissions are unsafe; configuration was not loaded")
        else:
            add("secrets:file_permissions", "NOT_CHECKED", "no .env file is present; environment-based configuration may be used")

        local_value = os.getenv("NETREGRESS_LOCAL_DIR", str(self.root / ".local"))
        local_candidate = Path(local_value).expanduser()
        if not local_candidate.is_absolute():
            local_candidate = self.root / local_candidate
        local_path_symlink = local_candidate.is_symlink()
        local_dir = local_candidate.resolve()

        auth_value = os.getenv("NETREGRESS_AUTH_REQUIRED", "0")
        if auth_value.strip().lower() not in {"0", "1", "true", "false", "yes", "no", "on", "off"}:
            add("authentication", "FAIL", "NETREGRESS_AUTH_REQUIRED must be a boolean value")
        elif self._is_true(auth_value):
            secret = os.getenv("NETREGRESS_SESSION_SECRET", "")
            users_value = os.getenv("NETREGRESS_AUTH_USERS_JSON", "")
            auth_path = local_candidate / "netregress-auth.json"
            session_path = local_candidate / "session-secret"
            if not local_path_symlink and not auth_path.is_symlink() and not users_value and auth_path.is_file():
                try:
                    users_value = auth_path.read_text(encoding="utf-8")
                except OSError:
                    users_value = ""
            if not local_path_symlink and not session_path.is_symlink() and not secret and session_path.is_file():
                try:
                    secret = session_path.read_text(encoding="utf-8").strip()
                except OSError:
                    secret = ""
            bootstrap_pending = (
                not secret
                and not users_value
                and not auth_path.exists()
                and not session_path.exists()
            )
            if bootstrap_pending:
                add(
                    "authentication",
                    "WARNING",
                    "first-run OWNER setup is pending; use scripts/start_dashboard.sh interactively before exposing the service",
                )
            else:
                auth_problems: list[str] = []
                if len(secret) < 32:
                    auth_problems.append("session signing secret must contain at least 32 characters")
                try:
                    users = json.loads(users_value)
                    valid_users = (
                        isinstance(users, list)
                        and bool(users)
                        and any(
                            isinstance(user, dict)
                            and str(user.get("role", "")).upper() in {"OWNER", "ADMIN"}
                            and isinstance(user.get("username"), str)
                            and bool(user.get("username"))
                            and isinstance(user.get("password_hash"), str)
                            and bool(user.get("password_hash"))
                            for user in users
                        )
                    )
                except (TypeError, ValueError):
                    valid_users = False
                if not valid_users:
                    auth_problems.append("authentication user configuration is missing or invalid")
                for credential_path in (auth_path, session_path):
                    if credential_path.is_symlink():
                        auth_problems.append(f"{credential_path.name} must not be a symlink")
                    elif credential_path.is_file() and (stat.S_IMODE(credential_path.stat().st_mode) & 0o077):
                        auth_problems.append(f"{credential_path.name} must be owner-readable only")
                add(
                    "authentication",
                    "FAIL" if auth_problems else "PASS",
                    "; ".join(auth_problems) if auth_problems else "required authentication and privileged user configuration are present",
                )
        else:
            add("authentication", "WARNING", "authentication is disabled; do not expose the dashboard beyond a trusted local environment")

        config_json = os.getenv("NETREGRESS_CONFIG_JSON", "").strip()
        if config_json:
            try:
                parsed = json.loads(config_json)
                valid_config = isinstance(parsed, dict)
            except ValueError:
                valid_config = False
            add(
                "configuration:json",
                "PASS" if valid_config else "FAIL",
                "NETREGRESS_CONFIG_JSON is a valid JSON object" if valid_config else "NETREGRESS_CONFIG_JSON must contain a JSON object",
            )
        else:
            add("configuration:json", "NOT_CHECKED", "no JSON override is configured")

        for relative in self.RUNTIME_DIRECTORIES:
            path = self.root / relative
            if path.is_symlink():
                add(f"storage:{relative}", "FAIL", "runtime directory must not be a symlink")
                continue
            if path.is_dir():
                writable = os.access(path, os.W_OK | os.X_OK)
                add(
                    f"storage:{relative}",
                    "PASS" if writable else "FAIL",
                    "directory is writable" if writable else "directory is not writable by the current user",
                )
            else:
                parent = path.parent
                while not parent.exists() and parent != parent.parent:
                    parent = parent.parent
                writable = parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)
                add(
                    f"storage:{relative}",
                    "WARNING" if writable else "FAIL",
                    "not initialized; parent is writable" if writable else "not initialized and no writable parent is available",
                )

        if local_path_symlink:
            add("storage:local_state", "FAIL", "local-state directory must not be a symlink")
        elif local_dir.is_dir():
            mode = stat.S_IMODE(local_dir.stat().st_mode)
            add(
                "storage:local_state",
                "PASS" if not (mode & 0o077) else "FAIL",
                "private local-state directory has owner-only permissions" if not (mode & 0o077) else "local-state directory permissions are too broad; require owner-only access",
            )
        else:
            add("storage:local_state", "WARNING", "local state directory has not been initialized")

        try:
            db_path = resolve_database_path(database, project_root=self.root)
        except DatabaseConfigurationError as exc:
            add("database:configuration", "FAIL", str(exc))
            db_path = None

        if db_path is not None and not db_path.is_file():
            add("database:integrity", "WARNING", "database is not initialized; run scripts/netregress_install.py")
            add("database:schema", "NOT_CHECKED", "schema migration state cannot be checked before database initialization")
        elif db_path is not None:
            try:
                connection = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=5)
                try:
                    row = connection.execute("PRAGMA integrity_check").fetchone()
                    integrity = str(row[0]) if row else "no result"
                finally:
                    connection.close()
                add(
                    "database:integrity",
                    "PASS" if integrity == "ok" else "FAIL",
                    "SQLite integrity_check=ok" if integrity == "ok" else f"SQLite integrity_check={integrity}",
                )
            except sqlite3.Error as exc:
                add("database:integrity", "FAIL", f"SQLite integrity check failed: {type(exc).__name__}")
            try:
                migration = DatabaseMigrationManager(db_path, project_root=self.root).check()
                add(
                    "database:schema",
                    "PASS" if migration.is_up_to_date else "FAIL",
                    f"schema revision {migration.current_revision or 'unversioned'}; expected {migration.head_revision}",
                )
            except Exception as exc:
                add("database:schema", "FAIL", f"migration state could not be verified: {type(exc).__name__}")

        package_json = self.root / "frontend" / "package.json"
        node = shutil.which("node")
        npm = shutil.which("npm")
        if package_json.is_file():
            try:
                package = json.loads(package_json.read_text(encoding="utf-8"))
                engines = package.get("engines", {}).get("node", "not specified")
            except (OSError, ValueError, AttributeError):
                engines = "invalid package.json"
                add("frontend:manifest", "FAIL", "frontend/package.json could not be parsed")
            else:
                add("frontend:manifest", "PASS", "frontend package manifest is valid")
            if node:
                import subprocess
                result = subprocess.run(
                    [node, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                version = result.stdout.strip().lstrip("v")
                supported = result.returncode == 0 and self._node_supported(version)
                add(
                    "frontend:node",
                    "PASS" if supported else "FAIL",
                    f"Node.js {version or 'unknown'}; supported engine range is {engines}",
                )
            else:
                add("frontend:node", "WARNING", f"Node.js is not installed; frontend cannot start (required range: {engines})")
            add(
                "frontend:npm",
                "PASS" if npm else "WARNING",
                "npm is available" if npm else "npm is not installed",
            )
            vite = self.root / "frontend" / "node_modules" / ".bin" / "vite"
            add(
                "frontend:dependencies",
                "PASS" if vite.exists() else "WARNING",
                "frontend dependencies are installed" if vite.exists() else "frontend dependencies are not installed; run npm install in frontend/",
            )
            package_lock = self.root / "frontend" / "package-lock.json"
            add(
                "frontend:lockfile",
                "PASS" if package_lock.is_file() else "WARNING",
                "npm lockfile is present" if package_lock.is_file() else "frontend/package-lock.json is missing; transitive frontend dependency resolution is not fully locked",
            )
        else:
            add("frontend:manifest", "FAIL", "frontend/package.json is missing")

        if include_lab_tools:
            for tool in self.LAB_TOOLS:
                available = shutil.which(tool) is not None
                add(
                    f"lab-tool:{tool}",
                    "PASS" if available else "FAIL",
                    "available" if available else "required tool is missing from PATH",
                )
        else:
            add("lab-tools", "NOT_CHECKED", "use --include-lab-tools to check protected-lab command prerequisites")

        if check_dashboard:
            try:
                backend_port = int(os.getenv("NETREGRESS_PORT", "5050"))
                frontend_port = int(os.getenv("NETREGRESS_FRONTEND_PORT", "5173"))
                if not (1024 <= backend_port <= 65535 and 1024 <= frontend_port <= 65535):
                    raise ValueError("dashboard ports must be between 1024 and 65535")
                if backend_port == frontend_port:
                    raise ValueError("backend and frontend ports must differ")
                with urlopen(f"http://127.0.0.1:{backend_port}/api/v1/health", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    healthy = response.status == 200 and payload.get("data", {}).get("status") == "ok"
                add("dashboard:api", "PASS" if healthy else "FAIL", "local API health endpoint returned the expected response" if healthy else "service health endpoint did not return the expected response")
                with urlopen(f"http://127.0.0.1:{frontend_port}/", timeout=2) as response:
                    body = response.read(131072).decode("utf-8", errors="replace")
                    healthy = response.status == 200 and 'id="root"' in body
                add("dashboard:frontend", "PASS" if healthy else "FAIL", "frontend root document is available" if healthy else "frontend root document is invalid")
            except (OSError, ValueError, URLError, json.JSONDecodeError) as exc:
                add("dashboard:runtime", "FAIL", f"dashboard runtime check failed: {type(exc).__name__}")
        else:
            add("dashboard:runtime", "NOT_CHECKED", "use --check-dashboard while the local dashboard is running")

        manifest_path = self.root / "results" / "release-manifest.json"
        if manifest_path.is_symlink():
            add("release:manifest", "FAIL", "release manifest must not be a symlink")
        elif manifest_path.is_file():
            try:
                from lib.services.release_manifest import ReleaseManifestService
                manifest_result = ReleaseManifestService(self.root).verify_manifest(manifest_path)
                if manifest_result["verified"]:
                    add("release:manifest", "PASS", "source-bound release manifest matches the current checkout")
                else:
                    mismatches = ", ".join(manifest_result.get("mismatches", ()))
                    add("release:manifest", "FAIL", "release manifest does not match the current checkout" + (f": {mismatches}" if mismatches else ""))
            except Exception as exc:
                add("release:manifest", "FAIL", f"release manifest could not be verified: {type(exc).__name__}")
        else:
            add("release:manifest", "NOT_CHECKED", "no generated source-bound release manifest is present")

        failures = sum(check.status == "FAIL" for check in checks)
        warnings = sum(check.status == "WARNING" for check in checks)
        unchecked = sum(check.status == "NOT_CHECKED" for check in checks)
        ready = failures == 0
        summary = (
            f"{len(checks)} checks: {failures} failed, {warnings} warning(s), "
            f"{unchecked} not checked"
        )
        return DoctorReport(tuple(checks), ready, summary)
