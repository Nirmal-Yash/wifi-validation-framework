from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


DEFAULT_REQUIRED_PATHS = (
    "README.md",
    ".gitignore",
    "requirements.txt",
    "docs/README.md",
    "docs/01_DEVELOPMENT_PLAN_AND_ROADMAP.md",
    "docs/02_SYSTEM_ARCHITECTURE_DATA_API.md",
    "docs/03_TRACEABILITY_AND_SYSTEM_READINESS.md",
    "docs/04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md",
    "docs/05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md",
    "docs/STANDALONE_INSTALLATION_AND_OPERATIONS.md",
    "docs/UPGRADE_AND_FIRST_RUN_GUIDE.md",
    "docs/SECURITY_AND_SAAS.md",
    "docs/openapi.yaml",
    "frontend/package.json",
    "frontend/index.html",
    "frontend/vite.config.js",
    "frontend/src/App.jsx",
    "frontend/src/api.js",
    "frontend/src/main.jsx",
    ".github/workflows/netregress-quality.yml",
    "scripts/ci_release_gate.py",
    "scripts/netregress_security_audit.py",
    "scripts/netregress_certification.py",
    "scripts/netregress_release.py",
    "scripts/netregress_doctor.py",
    "scripts/netregress_install.py",
    "scripts/netregress_sync.py",
    "scripts/start_dashboard.sh",
    "run_all.sh",
    "verify_system.py",
    "tests/test_standalone_operations.py",
    "tests/test_repository_governance.py",
    "tests/test_sync_queue.py",
    "tests/test_sync_service.py",
)
FORBIDDEN_TRACKED_SUFFIXES = (
    ".db", ".sqlite", ".sqlite3", ".pcap", ".pcapng", ".log", ".tmp", ".pyc",
    ".pem", ".key", ".p12", ".pfx",
)
FORBIDDEN_TRACKED_NAMES = {".env", ".env.local", ".env.production"}
FORBIDDEN_TRACKED_DIRECTORIES = ("results/", "artifacts/", ".robust-backups/", ".local/", "logs/", "captures/")


@dataclass(frozen=True, slots=True)
class ReleaseAudit:
    branch: str
    commit: str
    tree: str
    clean: bool
    required_paths_present: bool
    forbidden_tracked_files: tuple[str, ...]
    syntax_errors: tuple[str, ...]
    release_ready: bool


class ReleaseManifestService:
    """Build and verify deterministic, source-bound release metadata."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "git command failed")
        return result.stdout.strip()

    def tracked_files(self) -> tuple[str, ...]:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=self.root,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError("unable to enumerate tracked files")
        return tuple(item for item in result.stdout.decode().split("\0") if item)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _dependency_control(self) -> dict[str, Any]:
        requirements_path = self.root / "requirements.txt"
        direct_requirements: list[str] = []
        unpinned_requirements: list[str] = []
        if requirements_path.is_file():
            for raw in requirements_path.read_text(encoding="utf-8").splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line or line.startswith(("-", "http:", "https:")):
                    continue
                direct_requirements.append(line)
                pin_candidate = line.split(";", 1)[0].strip()
                if not re.match(r"^[A-Za-z0-9_.-]+(?:\[[^\]]+\])?==[^\s]+$", pin_candidate):
                    unpinned_requirements.append(line)

        package_path = self.root / "frontend" / "package.json"
        frontend_direct: list[str] = []
        frontend_unpinned: list[str] = []
        frontend_engine = None
        frontend_version = None
        if package_path.is_file():
            package = json.loads(package_path.read_text(encoding="utf-8"))
            frontend_version = package.get("version")
            frontend_engine = package.get("engines", {}).get("node")
            for section in ("dependencies", "devDependencies"):
                for name, version in sorted(package.get(section, {}).items()):
                    frontend_direct.append(f"{name}@{version}")
                    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
                        frontend_unpinned.append(f"{name}@{version}")

        # Only a lockfile committed to this checkout is part of the release input.
        # Local npm/pip tooling may create untracked lockfiles; they must not make
        # a source manifest claim dependency reproducibility.
        tracked_paths = set(self.tracked_files())
        python_lock = next(
            (
                name
                for name in ("requirements.lock", "requirements-full.lock", "uv.lock", "poetry.lock")
                if name in tracked_paths and (self.root / name).is_file()
            ),
            None,
        )
        frontend_lock = next(
            (
                name
                for name in ("frontend/package-lock.json", "frontend/pnpm-lock.yaml", "frontend/yarn.lock")
                if name in tracked_paths and (self.root / name).is_file()
            ),
            None,
        )
        python_direct_pinned = bool(direct_requirements) and not unpinned_requirements
        frontend_direct_pinned = bool(frontend_direct) and not frontend_unpinned
        lockfiles_present = bool(python_lock and frontend_lock)
        direct_dependencies_pinned = python_direct_pinned and frontend_direct_pinned
        complete = lockfiles_present and direct_dependencies_pinned
        if not lockfiles_present:
            dependency_status = "INCOMPLETE_TRANSITIVE_LOCKFILES"
        elif not direct_dependencies_pinned:
            dependency_status = "INCOMPLETE_DIRECT_DEPENDENCY_PINS"
        else:
            dependency_status = "COMPLETE"
        return {
            "python": {
                "requirements_file": "requirements.txt",
                "direct_dependency_count": len(direct_requirements),
                "direct_dependencies_pinned": python_direct_pinned,
                "unpinned_dependencies": unpinned_requirements,
                "transitive_lockfile": python_lock,
            },
            "frontend": {
                "package_version": frontend_version,
                "node_engine": frontend_engine,
                "direct_dependency_count": len(frontend_direct),
                "direct_dependencies_pinned": frontend_direct_pinned,
                "unpinned_dependencies": frontend_unpinned,
                "transitive_lockfile": frontend_lock,
            },
            "lockfiles_present": lockfiles_present,
            "direct_dependencies_pinned": direct_dependencies_pinned,
            "complete": complete,
            "status": dependency_status,
        }

    def audit(self) -> ReleaseAudit:
        branch = self._git("branch", "--show-current") or os.getenv("GITHUB_REF_NAME", "")
        commit = self._git("rev-parse", "HEAD")
        tree = self._git("rev-parse", "HEAD^{tree}")
        clean = not self._git("status", "--porcelain")
        tracked = self.tracked_files()
        forbidden = tuple(
            sorted(
                path
                for path in tracked
                if Path(path).name in FORBIDDEN_TRACKED_NAMES
                or (
                    Path(path).name.lower().startswith(".env")
                    and not Path(path).name.lower().endswith((".example", ".template"))
                )
                or Path(path).suffix.lower() in FORBIDDEN_TRACKED_SUFFIXES
                or path.startswith(FORBIDDEN_TRACKED_DIRECTORIES)
            )
        )
        required = all((self.root / path).is_file() for path in DEFAULT_REQUIRED_PATHS)
        errors: list[str] = []
        root_path = self.root.resolve()
        for relative in tracked:
            path = self.root / relative
            resolved = path.resolve(strict=False)
            if not resolved.is_relative_to(root_path):
                errors.append(f"{relative}: tracked path escapes the repository root")
                continue
            if relative.endswith(".py") and path.is_file():
                try:
                    compile(path.read_text(encoding="utf-8"), relative, "exec")
                except (OSError, SyntaxError) as exc:
                    errors.append(f"{relative}: {type(exc).__name__}: {exc}")
        ready = branch == "main" and clean and required and not forbidden and not errors
        return ReleaseAudit(
            branch=branch,
            commit=commit,
            tree=tree,
            clean=clean,
            required_paths_present=required,
            forbidden_tracked_files=forbidden,
            syntax_errors=tuple(sorted(errors)),
            release_ready=ready,
        )

    def manifest(self, *, audit: ReleaseAudit | None = None) -> dict[str, Any]:
        audit = audit or self.audit()
        dependency_control = self._dependency_control()
        files: list[dict[str, Any]] = []
        for relative in self.tracked_files():
            path = self.root / relative
            resolved = path.resolve(strict=False)
            if not path.is_file() or not resolved.is_relative_to(self.root):
                continue
            files.append(
                {
                    "path": relative,
                    "size_bytes": path.stat().st_size,
                    "sha256": self._sha256(path),
                }
            )
        revisions = sorted(
            path
            for path in self.tracked_files()
            if path.startswith("alembic/versions/") and path.endswith(".py")
        )
        source_security = {
            "forbidden_tracked_files": list(audit.forbidden_tracked_files),
            "syntax_errors": list(audit.syntax_errors),
        }
        return {
            "schema_version": "netregress-release-manifest.v2",
            "release_track": "standalone-runner",
            "application": {
                "name": "NetRegress Runner",
                "version": None,
                "version_status": "NOT_DECLARED_IN_REPOSITORY_METADATA",
                "frontend_package_version": dependency_control["frontend"]["package_version"],
            },
            "source": {
                "branch": audit.branch,
                "commit": audit.commit,
                "tree": audit.tree,
                "working_tree_clean": audit.clean,
            },
            "runtime_compatibility": {
                "python": ">=3.11",
                "node": dependency_control["frontend"]["node_engine"],
            },
            "dependencies": dependency_control,
            "database": {
                "migration_authority": "Alembic",
                "configuration": "alembic.ini",
                "migration_revisions": revisions,
            },
            "source_security": source_security,
            "required_paths_present": audit.required_paths_present,
            "release_ready": audit.release_ready,
            "production_reproducible": audit.release_ready and dependency_control["complete"],
            "tracked_file_count": len(files),
            "files": files,
        }

    def write_manifest(self, output: str | Path) -> Path:
        destination = Path(output).expanduser()
        if not destination.is_absolute():
            destination = self.root / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self.manifest()
        serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        return destination

    def verify_manifest(self, source: str | Path) -> dict[str, Any]:
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = self.root / path
        try:
            supplied = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {
                "verified": False,
                "mismatches": [f"manifest could not be read: {type(exc).__name__}"],
            }
        expected = self.manifest()
        mismatches = sorted(
            key
            for key in set(expected) | set(supplied if isinstance(supplied, dict) else {})
            if not isinstance(supplied, dict) or supplied.get(key) != expected.get(key)
        )
        digest = hashlib.sha256(
            json.dumps(supplied, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "verified": not mismatches,
            "manifest_sha256": digest,
            "mismatches": mismatches,
            "source_commit": expected["source"]["commit"],
        }
