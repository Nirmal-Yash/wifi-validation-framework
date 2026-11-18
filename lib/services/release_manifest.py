from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib
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

    @staticmethod
    def _canonical_package_name(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    @classmethod
    def _parse_pinned_requirements(
        cls,
        path: Path,
        *,
        require_hashes: bool,
    ) -> tuple[dict[str, str], list[str], list[str]]:
        """Parse the project's deliberately simple, exact-pin requirements format."""
        versions: dict[str, str] = {}
        errors: list[str] = []
        unhashed: list[str] = []
        hashed: set[str] = set()
        current_package: str | None = None
        if not path.is_file():
            return versions, [f"lockfile is missing: {path.name}"], unhashed

        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("--hash="):
                # pip-compile appends a continuation backslash when a package
                # has multiple hashes. Remove it before validating each hash.
                hash_line = line.removesuffix("\\").strip()
                if current_package is None:
                    errors.append(f"line {line_number}: hash is not attached to a package")
                elif re.fullmatch(r"--hash=sha256:[0-9a-fA-F]{64}", hash_line):
                    hashed.add(current_package)
                else:
                    errors.append(f"line {line_number}: unsupported or malformed package hash")
                continue
            if line.startswith("--"):
                continue

            requirement_line = line.split(" #", 1)[0].strip()
            requirement_line = requirement_line.removesuffix("\\").strip()
            match = re.fullmatch(
                r"([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?=="
                r"([A-Za-z0-9][A-Za-z0-9.!+_-]*)(?:\s*;.*)?",
                requirement_line,
            )
            if not match:
                errors.append(f"line {line_number}: requirement is not an exact package pin")
                current_package = None
                continue

            package_name = cls._canonical_package_name(match.group(1))
            version = match.group(2)
            previous = versions.get(package_name)
            if previous is not None and previous != version:
                errors.append(f"{package_name}: conflicting locked versions {previous} and {version}")
            versions[package_name] = version
            current_package = package_name
            if not require_hashes and "--hash=" in line:
                hashed.add(package_name)

        if require_hashes:
            unhashed = sorted(set(versions) - hashed)
            if unhashed:
                errors.append("packages without SHA-256 hashes: " + ", ".join(unhashed))
        return versions, errors, unhashed

    def _dependency_control(self) -> dict[str, Any]:
        requirements_path = self.root / "requirements.txt"
        direct_requirements: list[str] = []
        unpinned_requirements: list[str] = []
        direct_versions: dict[str, str] = {}
        if requirements_path.is_file():
            direct_versions, _, _ = self._parse_pinned_requirements(
                requirements_path, require_hashes=False
            )
            for raw in requirements_path.read_text(encoding="utf-8").splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line or line.startswith(("-", "http:", "https:")):
                    continue
                direct_requirements.append(line)
                pin_candidate = line.split(";", 1)[0].strip()
                if not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[^\]]+\])?==[^\s]+",
                    pin_candidate,
                ):
                    unpinned_requirements.append(line)

        package_path = self.root / "frontend" / "package.json"
        package: dict[str, Any] = {}
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
                    if not isinstance(version, str) or not re.fullmatch(
                        r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version
                    ):
                        frontend_unpinned.append(f"{name}@{version}")

        # Only source-controlled locks are release inputs. A local lockfile in
        # .git/info/exclude must never make the release look reproducible.
        tracked_paths = set(self.tracked_files())
        python_lock = (
            "requirements.lock"
            if "requirements.lock" in tracked_paths
            and (self.root / "requirements.lock").is_file()
            else None
        )
        frontend_lock = (
            "frontend/package-lock.json"
            if "frontend/package-lock.json" in tracked_paths
            and (self.root / "frontend/package-lock.json").is_file()
            else None
        )

        python_lock_errors: list[str] = []
        python_locked_count = 0
        if python_lock:
            locked_versions, python_lock_errors, unhashed = self._parse_pinned_requirements(
                self.root / python_lock, require_hashes=True
            )
            python_locked_count = len(locked_versions)
            for name, version in sorted(direct_versions.items()):
                if locked_versions.get(name) != version:
                    python_lock_errors.append(
                        f"{name}: requirements.txt pins {version}, lockfile has "
                        f"{locked_versions.get(name, 'no entry')}"
                    )

        frontend_lock_errors: list[str] = []
        frontend_locked_count = 0
        if frontend_lock:
            try:
                lock_payload = json.loads(
                    (self.root / frontend_lock).read_text(encoding="utf-8")
                )
                lock_packages = lock_payload.get("packages")
                lock_root = lock_packages.get("") if isinstance(lock_packages, dict) else None
                frontend_locked_count = max(0, len(lock_packages) - 1) if isinstance(lock_packages, dict) else 0
                if not isinstance(lock_payload.get("lockfileVersion"), int) or lock_payload["lockfileVersion"] < 2:
                    frontend_lock_errors.append("npm lockfileVersion must be 2 or newer")
                if not isinstance(lock_root, dict):
                    frontend_lock_errors.append("npm lockfile is missing packages[''] root metadata")
                else:
                    if lock_root.get("name") != package.get("name"):
                        frontend_lock_errors.append("npm lock root name does not match package.json")
                    if lock_root.get("version") != package.get("version"):
                        frontend_lock_errors.append("npm lock root version does not match package.json")
                    for section in ("dependencies", "devDependencies"):
                        expected = package.get(section, {})
                        observed = lock_root.get(section, {})
                        if expected != observed:
                            frontend_lock_errors.append(
                                f"npm lock root {section} do not match package.json"
                            )
                        for name, version in expected.items():
                            installed = lock_packages.get(f"node_modules/{name}") if isinstance(lock_packages, dict) else None
                            if not isinstance(installed, dict) or installed.get("version") != version:
                                frontend_lock_errors.append(
                                    f"{name}: package.json pins {version}, npm lock has "
                                    f"{installed.get('version', 'no entry') if isinstance(installed, dict) else 'no entry'}"
                                )
            except (OSError, ValueError, TypeError) as exc:
                frontend_lock_errors.append(f"npm lockfile could not be parsed: {type(exc).__name__}")

        python_direct_pinned = bool(direct_requirements) and not unpinned_requirements
        frontend_direct_pinned = bool(frontend_direct) and not frontend_unpinned
        runtime_lockfiles_present = bool(python_lock and frontend_lock)
        runtime_direct_dependencies_pinned = python_direct_pinned and frontend_direct_pinned
        runtime_lockfiles_valid = (
            bool(python_lock and frontend_lock)
            and not python_lock_errors
            and not frontend_lock_errors
        )
        runtime_complete = runtime_lockfiles_valid and runtime_direct_dependencies_pinned

        # Desktop build tooling is a separate dependency surface. A pinned
        # PyInstaller version alone does not lock its transitive dependencies.
        desktop_build_lock = (
            "requirements-desktop-build.lock"
            if "requirements-desktop-build.lock" in tracked_paths
            and (self.root / "requirements-desktop-build.lock").is_file()
            else None
        )
        desktop_build_lock_errors: list[str] = []
        desktop_build_locked_count = 0
        if desktop_build_lock:
            build_versions, desktop_build_lock_errors, _ = self._parse_pinned_requirements(
                self.root / desktop_build_lock, require_hashes=True
            )
            desktop_build_locked_count = len(build_versions)
            for raw in (self.root / "requirements-desktop-build.txt").read_text(encoding="utf-8").splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line or line.startswith(("-", "http:", "https:")):
                    continue
                candidate = line.split(";", 1)[0].strip()
                match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s]+)", candidate)
                if match and build_versions.get(match.group(1).lower().replace("_", "-")) != match.group(2):
                    desktop_build_lock_errors.append(
                        f"{match.group(1)}: build manifest pins {match.group(2)}, "
                        f"lockfile has {build_versions.get(match.group(1).lower().replace('_', '-'), 'no entry')}"
                    )
        else:
            desktop_build_lock_errors.append("lockfile is missing: requirements-desktop-build.lock")

        # Rust application dependencies must be source-locked as well. A valid
        # lock must describe this Tauri package, not just be present.
        cargo_lock = (
            "src-tauri/Cargo.lock"
            if "src-tauri/Cargo.lock" in tracked_paths
            and (self.root / "src-tauri" / "Cargo.lock").is_file()
            else None
        )
        cargo_lock_errors: list[str] = []
        cargo_locked_count = 0
        if cargo_lock:
            try:
                cargo_payload = tomllib.loads((self.root / cargo_lock).read_text(encoding="utf-8"))
                lock_version = cargo_payload.get("version")
                packages = cargo_payload.get("package")
                manifest_payload = json.loads((self.root / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
                manifest_version = manifest_payload.get("version")
                cargo_package = next(
                    (item for item in packages if item.get("name") == "netregress-runner"),
                    None,
                ) if isinstance(packages, list) else None
                cargo_locked_count = len(packages) if isinstance(packages, list) else 0
                if not isinstance(lock_version, int) or lock_version not in (3, 4):
                    cargo_lock_errors.append("Cargo.lock has an unsupported or missing lockfile version")
                if not isinstance(cargo_package, dict) or cargo_package.get("version") != manifest_version:
                    cargo_lock_errors.append("Cargo.lock does not contain the netregress-runner package at the desktop version")
                if not isinstance(cargo_package, dict) or not {"tauri", "tauri-build"}.issubset(
                    {str(item).split(" ", 1)[0] for item in cargo_package.get("dependencies", [])}
                ):
                    cargo_lock_errors.append("Cargo.lock is missing the direct Tauri build/runtime dependencies")
            except (OSError, ValueError, TypeError, StopIteration) as exc:
                cargo_lock_errors.append(f"Cargo.lock could not be validated: {type(exc).__name__}")
        else:
            cargo_lock_errors.append("lockfile is missing: src-tauri/Cargo.lock")

        build_lockfiles_present = bool(desktop_build_lock and cargo_lock)
        build_lockfiles_valid = (
            build_lockfiles_present
            and not desktop_build_lock_errors
            and not cargo_lock_errors
        )
        build_complete = build_lockfiles_valid
        complete = runtime_complete and build_complete

        if not runtime_lockfiles_present:
            dependency_status = "INCOMPLETE_RUNTIME_LOCKFILES"
        elif not runtime_direct_dependencies_pinned:
            dependency_status = "INCOMPLETE_DIRECT_DEPENDENCY_PINS"
        elif not runtime_lockfiles_valid:
            dependency_status = "RUNTIME_LOCKFILE_MISMATCH"
        elif not build_lockfiles_present:
            dependency_status = "INCOMPLETE_BUILD_LOCKFILES"
        elif not build_lockfiles_valid:
            dependency_status = "BUILD_LOCKFILE_MISMATCH"
        else:
            dependency_status = "COMPLETE"

        return {
            "python": {
                "requirements_file": "requirements.txt",
                "direct_dependency_count": len(direct_requirements),
                "direct_dependencies_pinned": python_direct_pinned,
                "unpinned_dependencies": unpinned_requirements,
                "transitive_lockfile": python_lock,
                "lockfile_valid": bool(python_lock) and not python_lock_errors,
                "locked_package_count": python_locked_count,
                "lockfile_errors": sorted(python_lock_errors),
            },
            "frontend": {
                "package_version": frontend_version,
                "node_engine": frontend_engine,
                "direct_dependency_count": len(frontend_direct),
                "direct_dependencies_pinned": frontend_direct_pinned,
                "unpinned_dependencies": frontend_unpinned,
                "transitive_lockfile": frontend_lock,
                "lockfile_valid": bool(frontend_lock) and not frontend_lock_errors,
                "locked_package_count": frontend_locked_count,
                "lockfile_errors": sorted(frontend_lock_errors),
            },
            "lockfiles_present": runtime_lockfiles_present,
            "lockfiles_valid": runtime_lockfiles_valid,
            "direct_dependencies_pinned": runtime_direct_dependencies_pinned,
            "runtime_complete": runtime_complete,
            "desktop_build": {
                "requirements_file": "requirements-desktop-build.txt",
                "transitive_lockfile": desktop_build_lock,
                "lockfile_valid": bool(desktop_build_lock) and not desktop_build_lock_errors,
                "locked_package_count": desktop_build_locked_count,
                "lockfile_errors": sorted(desktop_build_lock_errors),
            },
            "rust": {
                "manifest": "src-tauri/Cargo.toml",
                "transitive_lockfile": cargo_lock,
                "lockfile_valid": bool(cargo_lock) and not cargo_lock_errors,
                "locked_package_count": cargo_locked_count,
                "lockfile_errors": sorted(cargo_lock_errors),
            },
            "build_lockfiles_present": build_lockfiles_present,
            "build_lockfiles_valid": build_lockfiles_valid,
            "build_complete": build_complete,
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
        application_version = None
        application_version_status = "NOT_DECLARED_IN_REPOSITORY_METADATA"
        tauri_config_path = self.root / "src-tauri" / "tauri.conf.json"
        try:
            tauri_config = json.loads(tauri_config_path.read_text(encoding="utf-8"))
            candidate_version = tauri_config.get("version")
            if isinstance(candidate_version, str) and re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", candidate_version):
                application_version = candidate_version
                application_version_status = "DECLARED_IN_TAURI_CONFIGURATION"
        except (OSError, ValueError, TypeError):
            pass
        source_security = {
            "forbidden_tracked_files": list(audit.forbidden_tracked_files),
            "syntax_errors": list(audit.syntax_errors),
        }
        return {
            "schema_version": "netregress-release-manifest.v3",
            "release_track": "standalone-runner",
            "application": {
                "name": "NetRegress Runner",
                "version": application_version,
                "version_status": application_version_status,
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
