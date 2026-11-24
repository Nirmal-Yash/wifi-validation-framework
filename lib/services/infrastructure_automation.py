"""Scoped, approval-gated OpenTofu infrastructure automation.

Modules are operator-managed under NETREGRESS_OPENTOFU_MODULE_ROOT. Callers may
select a module and provide bounded non-secret variables; they cannot upload
arbitrary HCL, choose executables, select a backend, or supply CLI arguments.
Terraform state and binary plans are stored outside the repository in private
per-workspace directories and are never returned by an API.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
from typing import Any, Mapping

from lib.services.resource_lock import ResourceLockError, ResourceLockManager


class InfrastructureAutomationError(ValueError):
    """Invalid infrastructure workspace, module, plan or execution request."""


class InfrastructureAutomationNotFound(LookupError):
    """Workspace or plan is outside the requested Project/Lab scope."""


class InfrastructureAutomationConflict(InfrastructureAutomationError):
    """A stale, unapproved, locked or otherwise invalid lifecycle transition."""


@dataclass(frozen=True, slots=True)
class _TofuResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class OpenTofuRunner:
    """OpenTofu subprocess adapter. Commands are fixed argv arrays; shell is never used."""

    TIMEOUT_SECONDS = 600
    APPLY_TIMEOUT_SECONDS = 900

    def __init__(self, executable: str | None = None):
        self.executable = executable or os.environ.get("NETREGRESS_OPENTOFU_EXECUTABLE", "tofu")

    @staticmethod
    def _run(
        argv: list[str], *, cwd: Path, env: Mapping[str, str], timeout: int,
        stdout_limit: int = 16000,
    ) -> _TofuResult:
        try:
            result = subprocess.run(
                argv, cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=timeout, check=False,
                shell=False,
            )
            return _TofuResult(
                int(result.returncode), result.stdout[-stdout_limit:], result.stderr[-16000:], False,
            )
        except FileNotFoundError:
            return _TofuResult(127, "", "OpenTofu executable was not found", False)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
            return _TofuResult(124, stdout[-16000:], stderr[-16000:], True)

    @staticmethod
    def _env(workspace: Path) -> dict[str, str]:
        private = workspace / ".netregress"
        home = private / "home"
        plugin_cache = private / "plugin-cache"
        data_dir = private / "tofu-data"
        for directory in (home, plugin_cache, data_dir):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                directory.chmod(0o700)
            except OSError:
                pass
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(home),
            "TF_DATA_DIR": str(data_dir),
            "TF_PLUGIN_CACHE_DIR": str(plugin_cache),
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
            "TF_LOG": "OFF",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        # Cloud provider authentication is supplied by the operator process
        # identity only. Never accept credential values from API variables or
        # persist them in the workspace/state database.
        for name in (
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
            "AWS_DEFAULT_REGION", "AWS_REGION", "AWS_WEB_IDENTITY_TOKEN_FILE",
            "ARM_CLIENT_ID", "ARM_CLIENT_SECRET", "ARM_SUBSCRIPTION_ID",
            "ARM_TENANT_ID", "ARM_USE_MSI", "ARM_USE_OIDC",
            "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_PROJECT",
            "GOOGLE_REGION", "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
            "OS_AUTH_URL", "OS_USERNAME", "OS_PASSWORD", "OS_PROJECT_NAME",
            "OS_USER_DOMAIN_NAME", "OS_PROJECT_DOMAIN_NAME", "OS_REGION_NAME",
            "OS_APPLICATION_CREDENTIAL_ID", "OS_APPLICATION_CREDENTIAL_SECRET",
        ):
            value = os.environ.get(name)
            if value:
                env[name] = value
        return env

    def prepare(self, *, workspace: Path) -> dict:
        env = self._env(workspace)
        version = self._run([self.executable, "version"], cwd=workspace, env=env, timeout=30)
        version_text = (version.stdout + "\n" + version.stderr).strip()
        match = re.search(r"OpenTofu v([0-9]+)\.([0-9]+)(?:\.[0-9]+)?", version_text, re.I)
        if version.exit_code != 0 or not match:
            return {"valid": False, "code": "OPENTOFU_UNAVAILABLE", "message": "A supported OpenTofu CLI is unavailable"}
        version_tuple = (int(match.group(1)), int(match.group(2)))
        if version_tuple < (1, 8):
            return {"valid": False, "code": "OPENTOFU_VERSION_UNSUPPORTED", "message": "OpenTofu 1.8 or newer is required"}
        fmt = self._run(
            [self.executable, "fmt", "-check", "-diff", "-no-color"],
            cwd=workspace, env=env, timeout=60,
        )
        if fmt.exit_code != 0:
            return {"valid": False, "code": "OPENTOFU_FORMAT_INVALID", "message": "The approved module is not formatted"}
        init = self._run(
            [self.executable, "init", "-backend=false", "-input=false", "-no-color", "-lockfile=readonly"],
            cwd=workspace, env=env, timeout=self.TIMEOUT_SECONDS,
        )
        if init.exit_code != 0:
            return {"valid": False, "code": "OPENTOFU_INIT_FAILED", "message": "OpenTofu provider initialization failed"}
        validate = self._run(
            [self.executable, "validate", "-json"],
            cwd=workspace, env=env, timeout=self.TIMEOUT_SECONDS,
        )
        try:
            payload = json.loads(validate.stdout or "{}")
        except json.JSONDecodeError:
            payload = {}
        if validate.exit_code != 0 or payload.get("valid") is not True:
            return {"valid": False, "code": "OPENTOFU_VALIDATION_FAILED", "message": "OpenTofu configuration validation failed"}
        return {"valid": True, "code": "OPENTOFU_VALIDATED", "version": match.group(0)}

    def plan(
        self, *, workspace: Path, plan_file: str, destroy: bool = False,
        refresh_only: bool = False,
    ) -> dict:
        env = self._env(workspace)
        target = Path(plan_file)
        if target.is_absolute() or ".." in target.parts or not target.parts:
            raise InfrastructureAutomationError("plan file must be a safe workspace-relative path")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        argv = [
            self.executable, "plan", "-input=false", "-no-color",
            "-lock=true", "-lock-timeout=30s", "-detailed-exitcode",
            f"-out={target.as_posix()}",
        ]
        if destroy:
            argv.append("-destroy")
        if refresh_only:
            argv.append("-refresh-only")
        result = self._run(argv, cwd=workspace, env=env, timeout=self.TIMEOUT_SECONDS)
        if result.exit_code not in (0, 2):
            return {"valid": False, "code": "OPENTOFU_PLAN_FAILED", "message": "OpenTofu could not create a plan"}
        shown = self._run(
            [self.executable, "show", "-json", target.as_posix()],
            cwd=workspace, env=env, timeout=self.TIMEOUT_SECONDS, stdout_limit=8 * 1024 * 1024,
        )
        try:
            plan_json = json.loads(shown.stdout or "{}")
        except json.JSONDecodeError:
            plan_json = None
        if shown.exit_code != 0 or not isinstance(plan_json, dict):
            return {"valid": False, "code": "OPENTOFU_PLAN_UNREADABLE", "message": "OpenTofu plan review data is unavailable"}
        if target.exists():
            try:
                target.chmod(0o600)
            except OSError:
                pass
        return {"valid": True, "has_changes": result.exit_code == 2, "plan_json": plan_json}

    def apply(self, *, workspace: Path, plan_file: str) -> dict:
        target = Path(plan_file)
        if target.is_absolute() or ".." in target.parts or not target.parts:
            raise InfrastructureAutomationError("plan file must be a safe workspace-relative path")
        result = self._run(
            [self.executable, "apply", "-input=false", "-no-color", "-auto-approve", target.as_posix()],
            cwd=workspace, env=self._env(workspace), timeout=self.APPLY_TIMEOUT_SECONDS,
        )
        return {
            "success": result.exit_code == 0,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
        }

    def state_list(self, *, workspace: Path) -> list[str]:
        result = self._run(
            [self.executable, "state", "list"],
            cwd=workspace, env=self._env(workspace), timeout=120,
        )
        if result.exit_code == 0:
            return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
        if not (workspace / "terraform.tfstate").exists() and not (workspace / ".terraform").exists():
            return []
        if re.search(r"no state|state file.*not found|no state file", result.stderr, re.I):
            return []
        raise InfrastructureAutomationError("OpenTofu state inspection failed")

    def state_show(self, *, workspace: Path) -> dict:
        result = self._run(
            [self.executable, "show", "-json", "-no-color"],
            cwd=workspace, env=self._env(workspace), timeout=120, stdout_limit=8 * 1024 * 1024,
        )
        if result.exit_code != 0:
            if not (workspace / "terraform.tfstate").exists():
                return {"values": {"root_module": {"resources": []}}}
            raise InfrastructureAutomationError("OpenTofu state snapshot is unavailable")
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise InfrastructureAutomationError("OpenTofu returned an invalid state snapshot") from exc
        if not isinstance(payload, dict):
            raise InfrastructureAutomationError("OpenTofu returned an invalid state snapshot")
        return payload


class InfrastructureAutomationService:
    """Project/Lab-isolated OpenTofu workspaces and approval-gated lifecycle."""

    PLAN_TIMEOUT_SECONDS = OpenTofuRunner.TIMEOUT_SECONDS
    MAX_VARIABLE_BYTES = 65536
    MAX_MODULE_FILES = 512
    MAX_MODULE_BYTES = 20 * 1024 * 1024
    MODULE_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
    SECRET_KEY = re.compile(r"(password|passwd|secret|token|private.?key|api.?key|credential)", re.I)

    def __init__(
        self, database, *, runner=None, module_root: str | Path | None = None,
        state_root: str | Path | None = None, resource_lock_manager=None,
    ):
        self.database = database
        self.runner = runner or OpenTofuRunner()
        configured_modules = module_root or os.environ.get("NETREGRESS_OPENTOFU_MODULE_ROOT", "")
        self.module_root = Path(configured_modules).expanduser().resolve() if configured_modules else None
        configured_state = state_root or os.environ.get("NETREGRESS_OPENTOFU_STATE_ROOT", "")
        self.state_root = (
            Path(configured_state).expanduser().resolve()
            if configured_state else Path.home() / ".local" / "state" / "netregress" / "opentofu"
        )
        self.workspaces_root = self.state_root / "workspaces"
        self.workspaces_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._private_dir(self.state_root)
        self._private_dir(self.workspaces_root)
        self.resource_lock_manager = resource_lock_manager or ResourceLockManager(
            self.state_root / "locks"
        )

    @staticmethod
    def _private_dir(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            path.chmod(0o700)
        except OSError:
            pass

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
            raise InfrastructureAutomationError("actor must be a non-empty username")
        return value.strip()

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _digest(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @classmethod
    def _check_variable_keys(cls, value: object, depth: int = 0) -> None:
        if depth > 12:
            raise InfrastructureAutomationError("variables nesting exceeds 12 levels")
        if isinstance(value, dict):
            if len(value) > 256:
                raise InfrastructureAutomationError("variables object contains too many keys")
            for key, item in value.items():
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key):
                    raise InfrastructureAutomationError("variable names must be valid identifiers")
                if cls.SECRET_KEY.search(key):
                    raise InfrastructureAutomationError("secret values must not be supplied as OpenTofu variables")
                cls._check_variable_keys(item, depth + 1)
        elif isinstance(value, list):
            if len(value) > 2048:
                raise InfrastructureAutomationError("variable arrays exceed the supported size")
            for item in value:
                cls._check_variable_keys(item, depth + 1)
        elif isinstance(value, str) and len(value) > 8192:
            raise InfrastructureAutomationError("variable strings exceed 8192 characters")
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise InfrastructureAutomationError("variables must contain only JSON values")

    def _validate_variables(self, variables: object) -> dict:
        if variables is None:
            variables = {}
        if not isinstance(variables, dict):
            raise InfrastructureAutomationError("variables must be a JSON object")
        self._check_variable_keys(variables)
        try:
            encoded = self._canonical(variables).encode("utf-8")
        except (ValueError, TypeError) as exc:
            raise InfrastructureAutomationError("variables must be finite JSON values") from exc
        if len(encoded) > self.MAX_VARIABLE_BYTES:
            raise InfrastructureAutomationError("variables exceed the 64 KiB limit")
        return variables

    def _module_files(self, module_key: str) -> tuple[Path, list[Path], str]:
        if not isinstance(module_key, str) or not self.MODULE_KEY.fullmatch(module_key):
            raise InfrastructureAutomationError("module_key must be a safe lowercase module identifier")
        if self.module_root is None or not self.module_root.is_dir():
            raise InfrastructureAutomationConflict("OpenTofu module catalogue is not configured by the operator")
        try:
            root = self.module_root.resolve(strict=True)
            source = (root / module_key).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise InfrastructureAutomationError("requested operator-managed OpenTofu module was not found or is unsafe") from exc
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise InfrastructureAutomationError("module path escapes the operator-managed module root") from exc
        if source.is_symlink() or not source.is_dir():
            raise InfrastructureAutomationError("module must be an operator-managed directory")
        files = sorted(source.rglob("*"))
        regular_files: list[Path] = []
        total = 0
        has_configuration = False
        digest = hashlib.sha256()
        for path in files:
            if path.is_symlink():
                raise InfrastructureAutomationError("module symlinks are not permitted")
            if path.is_dir():
                continue
            if not path.is_file():
                raise InfrastructureAutomationError("module contains a non-regular file")
            relative = path.relative_to(source)
            if any(part in {"", ".", ".."} for part in relative.parts):
                raise InfrastructureAutomationError("module contains an unsafe path")
            if path.suffix not in {".tf", ".json", ".hcl"} and path.name != ".terraform.lock.hcl":
                continue
            size = path.stat().st_size
            total += size
            if len(regular_files) >= self.MAX_MODULE_FILES or total > self.MAX_MODULE_BYTES:
                raise InfrastructureAutomationError("module exceeds the file-count or size limit")
            if path.name.endswith(".tf") or path.name.endswith(".tf.json"):
                has_configuration = True
                try:
                    source_text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    raise InfrastructureAutomationError("module configuration must be readable UTF-8 text") from exc
                forbidden = (
                    r'''(?im)^\s*backend\s+["'][^"']+["']''',
                    r"(?im)^\s*cloud\s*\{",
                    r'''(?im)^\s*provisioner\s+["'][^"']+["']''',
                    r'''(?im)^\s*data\s+["']external["']''',
                    r"(?im)^\s*local-exec\s*\{",
                    r"(?im)^\s*remote-exec\s*\{",
                )
                if any(re.search(pattern, source_text) for pattern in forbidden):
                    raise InfrastructureAutomationError(
                        "module uses a prohibited backend, provisioner or external data source"
                    )
                for module in re.finditer(r'''(?is)module\s+"[^"]+"\s*\{(.*?)\}''', source_text):
                    match = re.search(r'''(?im)^\s*source\s*=\s*"([^"]+)"''', module.group(1))
                    if match is None or not match.group(1).startswith("./"):
                        raise InfrastructureAutomationError(
                            "only relative local OpenTofu modules inside the approved module root are permitted"
                        )
                    nested = (path.parent / match.group(1)).resolve()
                    try:
                        nested.relative_to(root)
                    except ValueError as exc:
                        raise InfrastructureAutomationError(
                            "local module source escapes the approved module root"
                        ) from exc
                if relative.parts[0] == ".netregress" or relative.as_posix() == "terraform.tfvars.json":
                    raise InfrastructureAutomationError("module cannot provide reserved NetRegress workspace files")
            regular_files.append(path)
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
        if not has_configuration:
            raise InfrastructureAutomationError("module must contain at least one .tf or .tf.json configuration file")
        return source, regular_files, digest.hexdigest()

    def list_modules(self) -> list[dict]:
        if self.module_root is None or not self.module_root.is_dir():
            return []
        items: list[dict] = []
        for path in sorted(self.module_root.iterdir()):
            if not path.is_dir() or path.is_symlink() or not self.MODULE_KEY.fullmatch(path.name):
                continue
            try:
                _, files, digest = self._module_files(path.name)
            except (InfrastructureAutomationError, OSError, UnicodeError):
                continue
            items.append({
                "module_key": path.name,
                "file_count": len(files),
                "module_sha256": digest,
            })
        return items

    def _workspace_path(self, workspace_id: str) -> Path:
        if not isinstance(workspace_id, str) or not re.fullmatch(r"[a-f0-9]{32}", workspace_id):
            raise InfrastructureAutomationError("workspace identifier is invalid")
        return self.workspaces_root / workspace_id

    @staticmethod
    def _audit(connection, actor: str, action: str, resource_id: str, details: dict) -> None:
        connection.execute(
            """INSERT INTO audit_events(
                audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                secrets.token_hex(16), actor, action, "OPENTOFU_WORKSPACE", resource_id,
                json.dumps(details, sort_keys=True, separators=(",", ":")), datetime.now(timezone.utc).isoformat(),
            ),
        )

    @staticmethod
    def _workspace_view(row) -> dict:
        return {
            "workspace_id": row["workspace_id"],
            "project_id": row["project_id"],
            "lab_id": row["lab_id"],
            "name": row["name"],
            "module_key": row["module_key"],
            "module_sha256": row["module_sha256"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "created_by": row["created_by"],
        }

    def create_workspace(
        self, *, project_id: str, lab_id: str, name: str, module_key: str,
        variables: object = None, actor: str,
    ) -> dict:
        actor = self._actor(actor)
        project_id = str(project_id or "").strip()
        lab_id = str(lab_id or "").strip()
        name = str(name or "").strip()
        if not project_id or not lab_id:
            raise InfrastructureAutomationError("project_id and lab_id are required")
        if not name or len(name) > 120:
            raise InfrastructureAutomationError("workspace name must contain 1 to 120 characters")
        safe_variables = self._validate_variables(variables)
        source, files, module_sha256 = self._module_files(module_key)
        now = self._now()
        workspace_id = secrets.token_hex(16)
        target = self._workspace_path(workspace_id)
        self._private_dir(target)
        try:
            for path in files:
                relative = path.relative_to(source)
                destination = target / relative
                self._private_dir(destination.parent)
                shutil.copyfile(path, destination)
                destination.chmod(0o600)
            tfvars = target / "terraform.tfvars.json"
            tfvars.write_text(self._canonical(safe_variables), encoding="utf-8")
            tfvars.chmod(0o600)
            manifest_root = target / ".netregress"
            self._private_dir(manifest_root)
            manifest = {
                "schema_version": 1,
                "module_sha256": module_sha256,
                "files": [
                    {
                        "path": path.relative_to(source).as_posix(),
                        "sha256": self._digest(path.read_bytes()),
                    }
                    for path in files
                ],
            }
            manifest_path = manifest_root / "module-manifest.json"
            manifest_path.write_text(self._canonical(manifest), encoding="utf-8")
            manifest_path.chmod(0o600)
            with self.database.transaction(immediate=True) as connection:
                lab = connection.execute(
                    """SELECT l.lab_id,l.project_id,l.status,p.status AS project_status
                       FROM labs l JOIN projects p ON p.project_id=l.project_id
                       WHERE l.lab_id=? AND l.project_id=?""",
                    (lab_id, project_id),
                ).fetchone()
                if lab is None:
                    raise InfrastructureAutomationNotFound("Lab not found in the selected Project")
                if lab["status"] != "ACTIVE" or lab["project_status"] != "ACTIVE":
                    raise InfrastructureAutomationConflict("only an active Project/Lab can own an OpenTofu workspace")
                connection.execute(
                    """INSERT INTO opentofu_workspaces(
                        workspace_id,project_id,lab_id,name,module_key,module_sha256,variables_json,
                        status,created_at,updated_at,created_by
                    ) VALUES(?,?,?,?,?,?,?,'ACTIVE',?,?,?)""",
                    (
                        workspace_id, project_id, lab_id, name, module_key, module_sha256,
                        self._canonical(safe_variables), now, now, actor,
                    ),
                )
                self._audit(connection, actor, "OPENTOFU_WORKSPACE_CREATED", workspace_id, {
                    "project_id": project_id, "lab_id": lab_id, "module_key": module_key,
                    "module_sha256": module_sha256,
                })
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return self.get_workspace(workspace_id)

    def get_workspace(self, workspace_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM opentofu_workspaces WHERE workspace_id=?", (workspace_id,)
            ).fetchone()
        return self._workspace_view(row) if row else None

    def list_workspaces(self, project_id: str, *, lab_id: str | None = None) -> list[dict]:
        query = "SELECT * FROM opentofu_workspaces WHERE project_id=?"
        params: list[object] = [project_id]
        if lab_id:
            query += " AND lab_id=?"
            params.append(lab_id)
        query += " ORDER BY created_at DESC,workspace_id"
        with self.database.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._workspace_view(row) for row in rows]

    def _workspace_row(self, workspace_id: str):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM opentofu_workspaces WHERE workspace_id=?", (workspace_id,)
            ).fetchone()
        if row is None:
            raise InfrastructureAutomationNotFound("OpenTofu workspace not found")
        return row

    def _verify_workspace_snapshot(self, row, workspace: Path) -> None:
        """Verify the private module and variable snapshot before every OpenTofu operation."""
        workspace = Path(workspace)
        workspace_id = row["workspace_id"]
        try:
            root = self.workspaces_root.resolve(strict=True)
            if self.workspaces_root.is_symlink() or workspace.is_symlink() or workspace.name != workspace_id:
                raise InfrastructureAutomationConflict("OpenTofu workspace path is unsafe")
            if workspace.parent.resolve(strict=True) != root:
                raise InfrastructureAutomationConflict("OpenTofu workspace escaped its private state root")
            resolved = workspace.resolve(strict=True)
            if resolved.parent != root or not resolved.is_dir():
                raise InfrastructureAutomationConflict("OpenTofu workspace path is unsafe")

            metadata_root = resolved / ".netregress"
            manifest_path = metadata_root / "module-manifest.json"
            if metadata_root.is_symlink() or not metadata_root.is_dir():
                raise InfrastructureAutomationConflict("module snapshot manifest directory is missing or unsafe")
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise InfrastructureAutomationConflict("module snapshot manifest is missing or unsafe")
            manifest_bytes = manifest_path.read_bytes()
            if not manifest_bytes or len(manifest_bytes) > 1_000_000:
                raise InfrastructureAutomationConflict("module snapshot manifest exceeds its integrity limit")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except InfrastructureAutomationError:
            raise
        except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise InfrastructureAutomationConflict("OpenTofu workspace snapshot is missing or unsafe") from exc

        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"schema_version", "module_sha256", "files"}
            or type(manifest.get("schema_version")) is not int
            or manifest.get("schema_version") != 1
            or manifest.get("module_sha256") != row["module_sha256"]
            or not isinstance(manifest.get("files"), list)
            or not 1 <= len(manifest["files"]) <= self.MAX_MODULE_FILES
        ):
            raise InfrastructureAutomationConflict("module snapshot manifest does not match the immutable workspace record")

        seen: set[str] = set()
        manifest_paths: list[str] = []
        total_bytes = 0
        module_digest = hashlib.sha256()
        for item in manifest["files"]:
            if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                raise InfrastructureAutomationConflict("module snapshot manifest contains an invalid file entry")
            relative_text = item["path"]
            expected_digest = item["sha256"]
            if (
                not isinstance(relative_text, str)
                or not relative_text
                or len(relative_text) > 512
                or "\\" in relative_text
                or not isinstance(expected_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
            ):
                raise InfrastructureAutomationConflict("module snapshot manifest contains an invalid path or SHA-256 digest")
            relative = PurePosixPath(relative_text)
            if (
                relative.is_absolute()
                or relative.as_posix() != relative_text
                or any(part in {"", ".", ".."} for part in relative.parts)
                or relative.parts[0] == ".netregress"
                or relative_text == "terraform.tfvars.json"
                or not (
                    relative.suffix in {".tf", ".json", ".hcl"}
                    or relative.name == ".terraform.lock.hcl"
                )
            ):
                raise InfrastructureAutomationConflict("module snapshot manifest contains an unsafe or unsupported file path")
            if relative_text in seen:
                raise InfrastructureAutomationConflict("module snapshot manifest contains a duplicate file path")
            seen.add(relative_text)
            manifest_paths.append(relative_text)

            candidate = resolved
            for part in relative.parts:
                candidate = candidate / part
                if candidate.is_symlink():
                    raise InfrastructureAutomationConflict("module snapshot file is a symlink")
            if not candidate.is_file():
                raise InfrastructureAutomationConflict("module snapshot file is missing")
            try:
                content = candidate.read_bytes()
            except OSError as exc:
                raise InfrastructureAutomationConflict("module snapshot file is unreadable") from exc
            total_bytes += len(content)
            if total_bytes > self.MAX_MODULE_BYTES:
                raise InfrastructureAutomationConflict("module snapshot exceeds its aggregate size limit")
            actual_digest = self._digest(content)
            if actual_digest != expected_digest:
                raise InfrastructureAutomationConflict("module snapshot file failed SHA-256 integrity verification")
            module_digest.update(relative_text.encode("utf-8"))
            module_digest.update(b"\0")
            module_digest.update(content)

        if manifest_paths != sorted(manifest_paths, key=lambda value: PurePosixPath(value).parts):
            raise InfrastructureAutomationConflict("module snapshot manifest file ordering is not canonical")

        # OpenTofu loads configuration files from the workspace directory. Reject
        # unmanifested files so a new .tf/.tf.json file cannot bypass the snapshot.
        actual_paths: list[str] = []
        try:
            for candidate in resolved.rglob("*"):
                relative = candidate.relative_to(resolved)
                if candidate.is_symlink():
                    raise InfrastructureAutomationConflict("module snapshot contains a symlink")
                if relative.parts and relative.parts[0] == ".netregress":
                    continue
                if candidate.is_dir():
                    continue
                if not candidate.is_file():
                    raise InfrastructureAutomationConflict("module snapshot contains a non-regular file")
                relative_text = relative.as_posix()
                if relative_text == "terraform.tfvars.json":
                    continue
                actual_paths.append(relative_text)
        except OSError as exc:
            raise InfrastructureAutomationConflict("module snapshot directory could not be inspected") from exc
        if len(actual_paths) != len(seen) or set(actual_paths) != seen:
            raise InfrastructureAutomationConflict("module snapshot contains unmanifested or missing files")
        if module_digest.hexdigest() != row["module_sha256"]:
            raise InfrastructureAutomationConflict("module snapshot failed its aggregate SHA-256 integrity check")

        variables_path = resolved / "terraform.tfvars.json"
        if variables_path.is_symlink() or not variables_path.is_file():
            raise InfrastructureAutomationConflict("variable snapshot failed integrity verification")
        try:
            variables_bytes = variables_path.read_bytes()
            if not variables_bytes or len(variables_bytes) > self.MAX_VARIABLE_BYTES:
                raise ValueError("variable file size is invalid")
            variables_text = variables_bytes.decode("utf-8")
            variables = self._validate_variables(json.loads(variables_text))
            canonical = self._canonical(variables)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, InfrastructureAutomationError) as exc:
            raise InfrastructureAutomationConflict("variable snapshot failed integrity verification") from exc
        if (
            variables_text != canonical
            or canonical != row["variables_json"]
            or self._digest(variables_bytes) != self._digest(canonical.encode("utf-8"))
        ):
            raise InfrastructureAutomationConflict("variable snapshot failed integrity verification")

    @staticmethod
    def _plan_summary(plan_json: dict, *, kind: str) -> dict:
        resource_changes = plan_json.get("resource_changes", [])
        if not isinstance(resource_changes, list):
            raise InfrastructureAutomationError("OpenTofu plan contains an invalid resource-change collection")
        changes = []
        requires_destroy = False
        for item in resource_changes:
            if not isinstance(item, dict):
                continue
            change = item.get("change")
            actions = change.get("actions", []) if isinstance(change, dict) else []
            if isinstance(actions, list) and "delete" in actions:
                requires_destroy = True
        for item in resource_changes[:2000]:
            if not isinstance(item, dict):
                continue
            address = item.get("address")
            resource_type = item.get("type")
            change = item.get("change")
            actions = change.get("actions", []) if isinstance(change, dict) else []
            if not isinstance(address, str) or not isinstance(resource_type, str) or not isinstance(actions, list):
                continue
            safe_actions = [action for action in actions if action in {"no-op", "create", "read", "update", "delete", "forget"}]
            changes.append({
                "address": address[:512],
                "resource_type": resource_type[:160],
                "actions": safe_actions,
            })
        output_changes = plan_json.get("output_changes")
        output_names = sorted(str(key)[:128] for key in output_changes.keys())[:256] if isinstance(output_changes, dict) else []
        return {
            "kind": kind,
            "resource_change_count": len(resource_changes),
            "resource_list_truncated": len(resource_changes) > len(changes),
            "resources": changes,
            "output_names": output_names,
            "requires_destroy_permission": requires_destroy,
        }

    def create_plan(
        self, workspace_id: str, *, kind: str = "APPLY", actor: str,
        reconciliation_id: str | None = None,
    ) -> dict:
        actor = self._actor(actor)
        kind = str(kind or "APPLY").upper()
        if kind not in {"APPLY", "DESTROY", "RECOVERY"}:
            raise InfrastructureAutomationError("plan kind must be APPLY, DESTROY or RECOVERY")
        row = self._workspace_row(workspace_id)
        if row["status"] == "DESTROYED":
            raise InfrastructureAutomationConflict("destroyed workspaces cannot create plans")
        if row["status"] == "RECOVERY_REQUIRED" and kind != "RECOVERY":
            raise InfrastructureAutomationConflict("workspace requires explicit recovery planning")
        if row["status"] == "ACTIVE" and kind == "RECOVERY":
            raise InfrastructureAutomationConflict("recovery plans are only valid for RECOVERY_REQUIRED workspaces")
        if kind == "RECOVERY":
            if not reconciliation_id:
                raise InfrastructureAutomationConflict("recovery planning requires a completed reconciliation snapshot")
            with self.database.connection() as connection:
                recovery_record = connection.execute(
                    """SELECT reconciliation_id FROM infrastructure_reconciliations
                       WHERE reconciliation_id=? AND workspace_id=? AND project_id=? AND lab_id=?""",
                    (reconciliation_id, workspace_id, row["project_id"], row["lab_id"]),
                ).fetchone()
                latest_record = connection.execute(
                    """SELECT reconciliation_id FROM infrastructure_reconciliations
                       WHERE workspace_id=? ORDER BY created_at DESC,reconciliation_id DESC LIMIT 1""",
                    (workspace_id,),
                ).fetchone()
            if recovery_record is None or latest_record is None or latest_record["reconciliation_id"] != reconciliation_id:
                raise InfrastructureAutomationConflict("recovery plan requires the latest reconciliation for this exact workspace")
        elif reconciliation_id is not None:
            raise InfrastructureAutomationError("only RECOVERY plans may reference a reconciliation snapshot")
        plan_id = secrets.token_hex(16)
        plan_relative = f".netregress/plans/{plan_id}.tfplan"
        workspace = self._workspace_path(workspace_id)
        if not workspace.is_dir():
            raise InfrastructureAutomationConflict("workspace files are missing; no OpenTofu command was started")
        try:
            lease = self.resource_lock_manager.acquire_many(
                [f"lab:{row['lab_id']}", f"opentofu-workspace:{workspace_id}"],
                f"{actor}:opentofu-plan:{plan_id}", timeout=0, lease_seconds=900,
            )
        except ResourceLockError as exc:
            raise InfrastructureAutomationConflict("Lab or OpenTofu workspace is locked; no plan was started") from exc
        try:
            self._verify_workspace_snapshot(row, workspace)
            prepared = self.runner.prepare(workspace=workspace)
            if not prepared.get("valid"):
                raise InfrastructureAutomationConflict(str(prepared.get("message") or "OpenTofu validation failed"))
            if kind == "RECOVERY":
                with self.database.connection() as connection:
                    current_reconciliation = connection.execute(
                        """SELECT reconciliation_id FROM infrastructure_reconciliations
                           WHERE workspace_id=? ORDER BY created_at DESC,reconciliation_id DESC LIMIT 1""",
                        (workspace_id,),
                    ).fetchone()
                if current_reconciliation is None or current_reconciliation["reconciliation_id"] != reconciliation_id:
                    raise InfrastructureAutomationConflict("a newer reconciliation replaced the selected recovery snapshot")
            planned = self.runner.plan(
                workspace=workspace, plan_file=plan_relative, destroy=kind == "DESTROY",
            )
            if not planned.get("valid") or not isinstance(planned.get("plan_json"), dict):
                raise InfrastructureAutomationConflict(str(planned.get("message") or "OpenTofu plan failed"))
            plan_path = workspace / plan_relative
            if not plan_path.is_file() or plan_path.is_symlink():
                raise InfrastructureAutomationConflict("OpenTofu did not produce a private plan artifact")
            plan_path.chmod(0o600)
            plan_bytes = plan_path.read_bytes()
            if not plan_bytes or len(plan_bytes) > 100 * 1024 * 1024:
                raise InfrastructureAutomationConflict("OpenTofu plan artifact is empty or exceeds the 100 MiB limit")
            plan_sha256 = self._digest(plan_bytes)
            summary = self._plan_summary(planned["plan_json"], kind=kind)
            now = self._now()
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO opentofu_plans(
                        plan_id,workspace_id,project_id,lab_id,kind,plan_sha256,plan_file,
                        summary_json,status,created_at,created_by,reconciliation_id
                    ) VALUES(?,?,?,?,?,?,?,?,'PREVIEWED',?,?,?)""",
                    (
                        plan_id, workspace_id, row["project_id"], row["lab_id"], kind,
                        plan_sha256, plan_relative, self._canonical(summary), now, actor,reconciliation_id,
                    ),
                )
                self._audit(connection, actor, "OPENTOFU_PLAN_CREATED", plan_id, {
                    "workspace_id": workspace_id, "kind": kind, "plan_sha256": plan_sha256,
                    "resource_change_count": summary["resource_change_count"],
                })
            return self.get_plan(plan_id)
        finally:
            lease.release()

    def get_plan(self, plan_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM opentofu_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if row is None:
                return None
            approval = connection.execute(
                "SELECT approval_id,plan_sha256,approved_by,confirmed_at FROM opentofu_approvals WHERE plan_id=? ORDER BY confirmed_at",
                (plan_id,),
            ).fetchall()
            executions = connection.execute(
                "SELECT execution_id,status,result_json,started_at,completed_at,executed_by FROM opentofu_executions WHERE plan_id=? ORDER BY started_at",
                (plan_id,),
            ).fetchall()
        workspace = self._workspace_path_for_plan(row)
        plan_file = row["plan_file"]
        if not isinstance(plan_file, str) or Path(plan_file).is_absolute() or ".." in Path(plan_file).parts:
            raise InfrastructureAutomationError("stored OpenTofu plan path failed validation")
        path = workspace / plan_file
        if not path.is_file() or path.is_symlink() or self._digest(path.read_bytes()) != row["plan_sha256"]:
            raise InfrastructureAutomationConflict("stored OpenTofu plan failed SHA-256 integrity verification")
        return {
            "plan_id": row["plan_id"],
            "workspace_id": row["workspace_id"],
            "project_id": row["project_id"],
            "lab_id": row["lab_id"],
            "kind": row["kind"],
            "reconciliation_id": row["reconciliation_id"],
            "plan_sha256": row["plan_sha256"],
            "summary": json.loads(row["summary_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "approved_at": row["approved_at"],
            "approved_by": row["approved_by"],
            "approvals": [dict(item) for item in approval],
            "executions": [
                {
                    "execution_id": item["execution_id"], "status": item["status"],
                    "result": json.loads(item["result_json"]),
                    "started_at": item["started_at"], "completed_at": item["completed_at"],
                    "executed_by": item["executed_by"],
                } for item in executions
            ],
        }

    def _workspace_path_for_plan(self, row) -> Path:
        path = self._workspace_path(row["workspace_id"])
        try:
            path.resolve(strict=True).relative_to(self.workspaces_root.resolve(strict=True))
        except (FileNotFoundError, ValueError) as exc:
            raise InfrastructureAutomationConflict("OpenTofu workspace path is unavailable or unsafe") from exc
        return path

    def list_plans(self, project_id: str, *, workspace_id: str | None = None, limit: int = 50) -> list[dict]:
        limit = max(1, min(int(limit), 200))
        query = "SELECT plan_id FROM opentofu_plans WHERE project_id=?"
        params: list[object] = [project_id]
        if workspace_id:
            query += " AND workspace_id=?"
            params.append(workspace_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [item for row in rows if (item := self.get_plan(row["plan_id"])) is not None]

    def approve(
        self, plan_id: str, *, expected_plan_sha256: str, confirmed: bool, actor: str,
    ) -> dict:
        actor = self._actor(actor)
        plan = self.get_plan(plan_id)
        if plan is None:
            raise InfrastructureAutomationNotFound("OpenTofu plan not found")
        if confirmed is not True:
            raise InfrastructureAutomationError("explicit confirmed=true is required")
        if expected_plan_sha256 != plan["plan_sha256"]:
            raise InfrastructureAutomationConflict("approval must match the exact reviewed plan SHA-256")
        if plan["status"] != "PREVIEWED":
            raise InfrastructureAutomationConflict("only a PREVIEWED OpenTofu plan can be approved")
        if actor == plan["created_by"]:
            raise InfrastructureAutomationConflict("plan creator cannot approve their own OpenTofu plan")
        approval_id = secrets.token_hex(16)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            current = connection.execute(
                "SELECT status,plan_sha256 FROM opentofu_plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if current is None:
                raise InfrastructureAutomationNotFound("OpenTofu plan not found")
            if current["status"] != "PREVIEWED" or current["plan_sha256"] != expected_plan_sha256:
                raise InfrastructureAutomationConflict("OpenTofu plan changed before approval")
            connection.execute(
                """INSERT INTO opentofu_approvals(
                    approval_id,plan_id,plan_sha256,approved_by,confirmed_at
                ) VALUES(?,?,?,?,?)""",
                (approval_id, plan_id, expected_plan_sha256, actor, now),
            )
            connection.execute(
                "UPDATE opentofu_plans SET status='APPROVED',approved_at=?,approved_by=? WHERE plan_id=?",
                (now, actor, plan_id),
            )
            self._audit(connection, actor, "OPENTOFU_PLAN_APPROVED", plan_id, {
                "plan_sha256": expected_plan_sha256, "approval_id": approval_id,
            })
        return self.get_plan(plan_id)

    def apply(
        self, plan_id: str, *, expected_plan_sha256: str, confirmed: bool, actor: str,
        destroy_authorized: bool = False,
    ) -> dict:
        actor = self._actor(actor)
        plan = self.get_plan(plan_id)
        if plan is None:
            raise InfrastructureAutomationNotFound("OpenTofu plan not found")
        if confirmed is not True:
            raise InfrastructureAutomationError("explicit confirmed=true is required")
        if plan["status"] != "APPROVED" or plan["plan_sha256"] != expected_plan_sha256:
            raise InfrastructureAutomationConflict("apply requires the exact independently approved plan hash")
        if not plan["approvals"] or plan["approvals"][-1]["approved_by"] == plan["created_by"]:
            raise InfrastructureAutomationConflict("independent approval evidence is missing")
        if (
            (plan["kind"] == "DESTROY" or plan["summary"]["requires_destroy_permission"])
            and destroy_authorized is not True
        ):
            raise InfrastructureAutomationConflict("plan contains resource deletion and requires explicit destroy-level authorization")
        row = self._workspace_row(plan["workspace_id"])
        if row["status"] == "DESTROYED":
            raise InfrastructureAutomationConflict("destroyed workspaces cannot be applied")
        workspace = self._workspace_path_for_plan_row(row)
        try:
            lease = self.resource_lock_manager.acquire_many(
                [f"lab:{row['lab_id']}", f"opentofu-workspace:{row['workspace_id']}"],
                f"{actor}:opentofu-apply:{plan_id}", timeout=0, lease_seconds=1800,
            )
        except ResourceLockError as exc:
            raise InfrastructureAutomationConflict("Lab or OpenTofu workspace is locked; no apply was started") from exc
        execution_id = secrets.token_hex(16)
        started = self._now()
        try:
            self._verify_workspace_snapshot(row, workspace)
            with self.database.transaction(immediate=True) as connection:
                current = connection.execute(
                    "SELECT status,plan_sha256 FROM opentofu_plans WHERE plan_id=?", (plan_id,)
                ).fetchone()
                approved = connection.execute(
                    "SELECT approval_id,approved_by FROM opentofu_approvals WHERE plan_id=? AND plan_sha256=?",
                    (plan_id, expected_plan_sha256),
                ).fetchone()
                if current is None or current["status"] != "APPROVED" or current["plan_sha256"] != expected_plan_sha256 or approved is None:
                    raise InfrastructureAutomationConflict("approved OpenTofu plan changed before apply")
                if row["status"] == "RECOVERY_REQUIRED" and plan["kind"] != "RECOVERY":
                    raise InfrastructureAutomationConflict("only an explicitly reviewed recovery plan may follow a partial apply")
                if row["status"] == "ACTIVE" and plan["kind"] == "RECOVERY":
                    raise InfrastructureAutomationConflict("recovery plan is no longer applicable")
                if plan["kind"] == "RECOVERY":
                    latest_reconciliation = connection.execute(
                        """SELECT reconciliation_id FROM infrastructure_reconciliations
                           WHERE workspace_id=? ORDER BY created_at DESC,reconciliation_id DESC LIMIT 1""",
                        (row["workspace_id"],),
                    ).fetchone()
                    if latest_reconciliation is None or latest_reconciliation["reconciliation_id"] != plan["reconciliation_id"]:
                        raise InfrastructureAutomationConflict("a newer reconciliation made this recovery plan stale")
                plan_row = connection.execute(
                    "SELECT plan_file FROM opentofu_plans WHERE plan_id=?", (plan_id,)
                ).fetchone()
                if plan_row is None:
                    raise InfrastructureAutomationNotFound("OpenTofu plan not found")
                plan_file = plan_row["plan_file"]
                plan_path = workspace / plan_file
                if not plan_path.is_file() or plan_path.is_symlink() or self._digest(plan_path.read_bytes()) != expected_plan_sha256:
                    raise InfrastructureAutomationConflict("OpenTofu plan artifact changed; apply is blocked")
                connection.execute("UPDATE opentofu_plans SET status='APPLYING' WHERE plan_id=?", (plan_id,))
                connection.execute(
                    """INSERT INTO opentofu_executions(
                        execution_id,plan_id,plan_sha256,status,result_json,started_at,executed_by
                    ) VALUES(?,?,?,'RUNNING','{}',?,?)""",
                    (execution_id, plan_id, expected_plan_sha256, started, actor),
                )
                self._audit(connection, actor, "OPENTOFU_APPLY_STARTED", plan_id, {
                    "execution_id": execution_id, "kind": plan["kind"], "plan_sha256": expected_plan_sha256,
                })
            try:
                result = self.runner.apply(workspace=workspace, plan_file=plan_file)
            except Exception as exc:
                # An exception or timeout after apply starts is an uncertain
                # partial-change boundary, never a safe automatic retry.
                result = {
                    "success": False, "exit_code": 1, "timed_out": False,
                    "failure_class": type(exc).__name__,
                }
            success = result.get("success") is True
            completed = self._now()
            result_summary = {
                "success": success,
                "exit_code": int(result.get("exit_code", 1)),
                "timed_out": bool(result.get("timed_out", False)),
                "possible_partial_change": not success,
                "recovery_required": not success,
            }
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    "UPDATE opentofu_plans SET status=? WHERE plan_id=?",
                    ("APPLIED" if success else "FAILED", plan_id),
                )
                connection.execute(
                    "UPDATE opentofu_executions SET status=?,result_json=?,completed_at=? WHERE execution_id=?",
                    ("SUCCEEDED" if success else "FAILED", self._canonical(result_summary), completed, execution_id),
                )
                next_status = "DESTROYED" if success and plan["kind"] == "DESTROY" else (
                    "ACTIVE" if success else "RECOVERY_REQUIRED"
                )
                connection.execute(
                    "UPDATE opentofu_workspaces SET status=?,updated_at=? WHERE workspace_id=?",
                    (next_status, completed, row["workspace_id"]),
                )
                self._audit(connection, actor, "OPENTOFU_APPLY_SUCCEEDED" if success else "OPENTOFU_APPLY_FAILED", plan_id, {
                    "execution_id": execution_id, **result_summary,
                })
            return self.get_plan(plan_id)
        finally:
            lease.release()

    def _workspace_path_for_plan_row(self, row) -> Path:
        path = self._workspace_path(row["workspace_id"])
        try:
            path.resolve(strict=True).relative_to(self.workspaces_root.resolve(strict=True))
        except (FileNotFoundError, ValueError) as exc:
            raise InfrastructureAutomationConflict("OpenTofu workspace path is unavailable or unsafe") from exc
        if path.is_symlink() or not path.is_dir():
            raise InfrastructureAutomationConflict("OpenTofu workspace directory is missing or unsafe")
        return path

    @staticmethod
    def _state_resources(state: dict) -> list[dict]:
        values = state.get("values") if isinstance(state, dict) else None
        root = values.get("root_module") if isinstance(values, dict) else None
        found: dict[str, dict] = {}

        def visit(module: object) -> None:
            if not isinstance(module, dict):
                return
            resources = module.get("resources", [])
            if isinstance(resources, list):
                for resource in resources:
                    if not isinstance(resource, dict):
                        continue
                    address = resource.get("address")
                    resource_type = resource.get("type")
                    if isinstance(address, str) and address and isinstance(resource_type, str) and resource_type:
                        found[address] = {"resource_address": address[:512], "resource_type": resource_type[:160]}
            children = module.get("child_modules", [])
            if isinstance(children, list):
                for child in children:
                    visit(child)

        visit(root)
        return [found[key] for key in sorted(found)]

    @staticmethod
    def _drift_resources(plan_json: dict) -> dict[str, dict]:
        raw = plan_json.get("resource_drift", [])
        if not isinstance(raw, list):
            raise InfrastructureAutomationError("OpenTofu refresh plan contains an invalid resource-drift collection")
        result: dict[str, dict] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            address = item.get("address")
            resource_type = item.get("type")
            change = item.get("change")
            actions = change.get("actions", []) if isinstance(change, dict) else []
            if not isinstance(address, str) or not address or not isinstance(actions, list):
                continue
            safe_actions = [
                action for action in actions
                if action in {"no-op", "create", "read", "update", "delete", "forget"}
            ]
            result[address] = {
                "resource_type": resource_type[:160] if isinstance(resource_type, str) else "",
                "actions": safe_actions,
            }
        return result

    def _workspace_lock(self, row, workspace_id: str, actor: str, purpose: str, seconds: int = 600):
        try:
            return self.resource_lock_manager.acquire_many(
                [f"lab:{row['lab_id']}", f"opentofu-workspace:{workspace_id}"],
                f"{actor}:opentofu-{purpose}:{secrets.token_hex(8)}",
                timeout=0, lease_seconds=seconds,
            )
        except ResourceLockError as exc:
            raise InfrastructureAutomationConflict(
                f"Lab or OpenTofu workspace is locked; {purpose} was not started"
            ) from exc

    def create_resource_binding(
        self, workspace_id: str, *, resource_address: str, topology_profile_id: str,
        topology_revision_id: str, topology_node_id: str, actor: str,
        expected_current_binding_id: str | None = None,
    ) -> dict:
        actor = self._actor(actor)
        if expected_current_binding_id is not None and (
            not isinstance(expected_current_binding_id, str)
            or not re.fullmatch(r"[a-f0-9]{32}", expected_current_binding_id)
        ):
            raise InfrastructureAutomationError("expected_current_binding_id must be a valid binding identifier")
        values = {
            "resource_address": resource_address,
            "topology_profile_id": topology_profile_id,
            "topology_revision_id": topology_revision_id,
            "topology_node_id": topology_node_id,
        }
        limits = {
            "resource_address": 512, "topology_profile_id": 128,
            "topology_revision_id": 128, "topology_node_id": 64,
        }
        for key, value in values.items():
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > limits[key]:
                raise InfrastructureAutomationError(f"{key} must contain 1 to {limits[key]} characters")
            values[key] = value.strip()
            if any(ord(char) < 32 for char in values[key]):
                raise InfrastructureAutomationError(f"{key} cannot contain control characters")
        row = self._workspace_row(workspace_id)
        if row["status"] == "DESTROYED":
            raise InfrastructureAutomationConflict("destroyed workspaces cannot receive resource mappings")
        workspace = self._workspace_path_for_plan_row(row)
        lease = self._workspace_lock(row, workspace_id, actor, "resource-mapping", 300)
        try:
            self._verify_workspace_snapshot(row, workspace)
            prepared = self.runner.prepare(workspace=workspace)
            if not prepared.get("valid"):
                raise InfrastructureAutomationConflict(
                    str(prepared.get("message") or "OpenTofu workspace could not be prepared for resource mapping")
                )
            state = self.runner.state_show(workspace=workspace)
            resources = self._state_resources(state)
            resource = next(
                (item for item in resources if item["resource_address"] == values["resource_address"]),
                None,
            )
            if resource is None:
                raise InfrastructureAutomationConflict(
                    "resource address is not present in this workspace's observed OpenTofu state"
                )
            with self.database.connection() as connection:
                profile = connection.execute(
                    "SELECT * FROM topology_profiles WHERE profile_id=?",
                    (values["topology_profile_id"],),
                ).fetchone()
                revision = connection.execute(
                    "SELECT * FROM topology_revisions WHERE revision_id=? AND profile_id=?",
                    (values["topology_revision_id"], values["topology_profile_id"]),
                ).fetchone()
            if profile is None or revision is None or profile["project_id"] != row["project_id"]:
                raise InfrastructureAutomationNotFound(
                    "topology profile or revision was not found in the workspace Project"
                )
            if profile["status"] != "ACTIVE" or revision["status"] != "PUBLISHED":
                raise InfrastructureAutomationConflict(
                    "resource mappings require an active topology profile and a published immutable revision"
                )
            if profile["scope_type"] == "LAB" and profile["lab_id"] != row["lab_id"]:
                raise InfrastructureAutomationConflict(
                    "Lab-scoped topology profile belongs to a different Lab"
                )
            if profile["scope_type"] not in {"LAB", "PROJECT"}:
                raise InfrastructureAutomationConflict("topology profile has an unsupported ownership scope")
            try:
                definition = json.loads(revision["definition_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise InfrastructureAutomationConflict("published topology revision content is invalid") from exc
            _, encoded, digest = self._topology_payload(definition)
            if digest != revision["content_sha256"] or encoded != revision["definition_json"]:
                raise InfrastructureAutomationConflict("published topology revision failed content integrity verification")
            nodes = definition.get("nodes", []) if isinstance(definition, dict) else []
            node = next(
                (item for item in nodes if isinstance(item, dict) and item.get("id") == values["topology_node_id"]),
                None,
            )
            if node is None:
                raise InfrastructureAutomationNotFound(
                    "logical topology node was not found in the selected published revision"
                )
            binding_id = secrets.token_hex(16)
            now = self._now()
            with self.database.transaction(immediate=True) as connection:
                current = connection.execute(
                    """SELECT * FROM infrastructure_resource_bindings
                       WHERE workspace_id=? AND resource_address=? AND status='ACTIVE'""",
                    (workspace_id, values["resource_address"]),
                ).fetchone()
                same_mapping = current is not None and (
                    current["topology_profile_id"] == values["topology_profile_id"]
                    and current["topology_revision_id"] == values["topology_revision_id"]
                    and current["topology_node_id"] == values["topology_node_id"]
                )
                if same_mapping:
                    if expected_current_binding_id not in (None, current["binding_id"]):
                        raise InfrastructureAutomationConflict("expected current binding does not match the active mapping")
                    binding_id = current["binding_id"]
                else:
                    if current is not None and expected_current_binding_id != current["binding_id"]:
                        raise InfrastructureAutomationConflict(
                            "resource already has a different active topology mapping; provide its expected binding ID to replace it"
                        )
                    if current is None and expected_current_binding_id is not None:
                        raise InfrastructureAutomationConflict("expected current binding is stale; no active mapping exists")
                    is_replacement = current is not None
                    connection.execute(
                        """INSERT INTO infrastructure_resource_bindings(
                            binding_id,workspace_id,project_id,lab_id,resource_address,resource_type,
                            topology_profile_id,topology_revision_id,topology_node_id,status,superseded_by,
                            created_at,created_by
                        ) VALUES(?,?,?,?,?,?,?,?,?,'PENDING',NULL,?,?)""",
                        (
                            binding_id, workspace_id, row["project_id"], row["lab_id"],
                            values["resource_address"], resource["resource_type"],
                            values["topology_profile_id"], values["topology_revision_id"],
                            values["topology_node_id"], now, actor,
                        ),
                    )
                    if current is not None:
                        cursor = connection.execute(
                            """UPDATE infrastructure_resource_bindings
                               SET status='SUPERSEDED',superseded_by=?
                               WHERE binding_id=? AND status='ACTIVE'""",
                            (binding_id, current["binding_id"]),
                        )
                        if cursor.rowcount != 1:
                            raise InfrastructureAutomationConflict("active resource mapping changed during replacement")
                    cursor = connection.execute(
                        """UPDATE infrastructure_resource_bindings SET status='ACTIVE'
                           WHERE binding_id=? AND status='PENDING'""",
                        (binding_id,),
                    )
                    if cursor.rowcount != 1:
                        raise InfrastructureAutomationConflict("new resource mapping could not be activated")
                    self._audit(connection, actor, "INFRASTRUCTURE_RESOURCE_REBOUND" if is_replacement else "INFRASTRUCTURE_RESOURCE_BOUND", binding_id, {
                        "workspace_id": workspace_id, "resource_address": values["resource_address"],
                        "resource_type": resource["resource_type"],
                        "topology_profile_id": values["topology_profile_id"],
                        "topology_revision_id": values["topology_revision_id"],
                        "topology_node_id": values["topology_node_id"],
                        "supersedes_binding_id": current["binding_id"] if current is not None else None,
                    })
        except InfrastructureAutomationError:
            raise
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise InfrastructureAutomationConflict(
                    "an OpenTofu resource address is already mapped in this workspace"
                ) from exc
            if "FOREIGN KEY constraint failed" in str(exc):
                raise InfrastructureAutomationNotFound(
                    "workspace or topology revision no longer exists"
                ) from exc
            if "infrastructure resource binding must target" in str(exc).lower():
                raise InfrastructureAutomationConflict(str(exc)) from exc
            raise
        finally:
            lease.release()
        return self.get_resource_binding(workspace_id, binding_id)

    @staticmethod
    def _topology_payload(definition: object) -> tuple[dict, str, str]:
        if not isinstance(definition, dict) or not isinstance(definition.get("nodes"), list) or not isinstance(definition.get("links"), list):
            raise InfrastructureAutomationConflict("published topology revision has an invalid definition shape")
        encoded = json.dumps(
            definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return definition, encoded, digest

    def get_resource_binding(self, workspace_id: str, binding_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT * FROM infrastructure_resource_bindings
                   WHERE workspace_id=? AND binding_id=?""",
                (workspace_id, binding_id),
            ).fetchone()
        if row is None:
            return None
        return {key: row[key] for key in (
            "binding_id", "workspace_id", "project_id", "lab_id", "resource_address",
            "resource_type", "topology_profile_id", "topology_revision_id",
            "topology_node_id", "status", "superseded_by", "created_at", "created_by",
        )}

    def list_resource_bindings(self, workspace_id: str) -> dict:
        row = self._workspace_row(workspace_id)
        with self.database.connection() as connection:
            bindings = connection.execute(
                """SELECT * FROM infrastructure_resource_bindings
                   WHERE workspace_id=? ORDER BY resource_address,binding_id""",
                (workspace_id,),
            ).fetchall()
            latest = connection.execute(
                """SELECT * FROM infrastructure_reconciliations
                   WHERE workspace_id=? ORDER BY created_at DESC,reconciliation_id DESC LIMIT 1""",
                (workspace_id,),
            ).fetchone()
        observation_items = {}
        if latest is not None:
            observation_items = {
                item["resource_address"]: item
                for item in json.loads(latest["details_json"]).get("resources", [])
                if isinstance(item, dict) and isinstance(item.get("resource_address"), str)
            }
        result = []
        for item in bindings:
            view = {
                key: item[key] for key in (
                    "binding_id", "workspace_id", "project_id", "lab_id", "resource_address",
                    "resource_type", "topology_profile_id", "topology_revision_id",
                    "topology_node_id", "status", "superseded_by", "created_at", "created_by",
                )
            }
            observation = observation_items.get(item["resource_address"], {})
            view["observed_status"] = (
                observation.get("status", "UNKNOWN")
                if item["status"] == "ACTIVE" else "HISTORICAL"
            )
            view["observed_at"] = latest["created_at"] if latest is not None else None
            result.append(view)
        return {
            "workspace_id": workspace_id,
            "project_id": row["project_id"],
            "lab_id": row["lab_id"],
            "items": result,
            "latest_reconciliation": self._reconciliation_view(latest) if latest is not None else None,
        }

    @staticmethod
    def _reconciliation_view(row) -> dict | None:
        if row is None:
            return None
        details = json.loads(row["details_json"])
        return {
            "reconciliation_id": row["reconciliation_id"],
            "workspace_id": row["workspace_id"],
            "project_id": row["project_id"],
            "lab_id": row["lab_id"],
            "status": row["status"],
            "state_sha256": row["state_sha256"],
            "refresh_plan_sha256": row["refresh_plan_sha256"],
            "resource_count": row["resource_count"],
            "drift_count": row["drift_count"],
            "orphan_count": row["orphan_count"],
            "missing_count": row["missing_count"],
            "details": details,
            "created_at": row["created_at"],
            "created_by": row["created_by"],
        }

    def reconcile(self, workspace_id: str, *, actor: str) -> dict:
        actor = self._actor(actor)
        row = self._workspace_row(workspace_id)
        if row["status"] == "DESTROYED":
            raise InfrastructureAutomationConflict("destroyed workspaces cannot be reconciled")
        workspace = self._workspace_path_for_plan_row(row)
        lease = self._workspace_lock(row, workspace_id, actor, "reconcile", 900)
        try:
            self._verify_workspace_snapshot(row, workspace)
            prepared = self.runner.prepare(workspace=workspace)
            if not prepared.get("valid"):
                raise InfrastructureAutomationConflict(
                    str(prepared.get("message") or "OpenTofu workspace could not be validated for reconciliation")
                )
            reconciliation_id = secrets.token_hex(16)
            plan_relative = f".netregress/reconciliations/{reconciliation_id}.tfplan"
            planned = self.runner.plan(
                workspace=workspace, plan_file=plan_relative, refresh_only=True,
            )
            if not planned.get("valid") or not isinstance(planned.get("plan_json"), dict):
                raise InfrastructureAutomationConflict(
                    str(planned.get("message") or "OpenTofu refresh-only plan failed")
                )
            plan_path = workspace / plan_relative
            if not plan_path.is_file() or plan_path.is_symlink():
                raise InfrastructureAutomationConflict("OpenTofu refresh-only plan artifact is missing or unsafe")
            plan_path.chmod(0o600)
            plan_bytes = plan_path.read_bytes()
            if not plan_bytes or len(plan_bytes) > 100 * 1024 * 1024:
                raise InfrastructureAutomationConflict("OpenTofu refresh-only plan exceeds the 100 MiB limit")
            state = self.runner.state_show(workspace=workspace)
            if not isinstance(state, dict):
                raise InfrastructureAutomationConflict("OpenTofu state snapshot is not a JSON object")
            try:
                state_encoded = self._canonical(state).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise InfrastructureAutomationConflict("OpenTofu state snapshot is not canonical JSON") from exc
            state_sha256 = self._digest(state_encoded)
            state_resources = self._state_resources(state)
            if len(state_resources) > 100000:
                raise InfrastructureAutomationConflict("OpenTofu state contains more than 100,000 resources; reconciliation is blocked")
            drift = self._drift_resources(planned["plan_json"])
            if len(drift) > 100000:
                raise InfrastructureAutomationConflict("OpenTofu refresh plan reports more than 100,000 drift observations; reconciliation is blocked")
            with self.database.connection() as connection:
                binding_rows = connection.execute(
                    "SELECT * FROM infrastructure_resource_bindings WHERE workspace_id=? AND status='ACTIVE' ORDER BY resource_address",
                    (workspace_id,),
                ).fetchall()
            if len(binding_rows) > 100000:
                raise InfrastructureAutomationConflict("workspace has more than 100,000 topology resource bindings; reconciliation is blocked")
            bindings = {item["resource_address"]: item for item in binding_rows}
            state_by_address = {item["resource_address"]: item for item in state_resources}
            resources = []
            drift_count = orphan_count = missing_count = 0
            for address, resource in sorted(state_by_address.items()):
                binding = bindings.get(address)
                drift_item = drift.get(address)
                if drift_item:
                    drift_count += 1
                if binding is None:
                    orphan_count += 1
                status = (
                    "DRIFTED_ORPHANED" if drift_item and binding is None
                    else "DRIFTED" if drift_item
                    else "ORPHANED" if binding is None
                    else "PRESENT"
                )
                resources.append({
                    "resource_address": address,
                    "resource_type": resource["resource_type"],
                    "status": status,
                    "is_drifted": bool(drift_item),
                    "is_orphaned": binding is None,
                    "drift_actions": drift_item.get("actions", []) if drift_item else [],
                    "binding_id": binding["binding_id"] if binding is not None else None,
                    "topology_profile_id": binding["topology_profile_id"] if binding is not None else None,
                    "topology_revision_id": binding["topology_revision_id"] if binding is not None else None,
                    "topology_node_id": binding["topology_node_id"] if binding is not None else None,
                })
            for address, binding in sorted(bindings.items()):
                if address not in state_by_address:
                    missing_count += 1
                    resources.append({
                        "resource_address": address,
                        "resource_type": binding["resource_type"],
                        "status": "MISSING",
                        "drift_actions": [],
                        "binding_id": binding["binding_id"],
                        "topology_profile_id": binding["topology_profile_id"],
                        "topology_revision_id": binding["topology_revision_id"],
                        "topology_node_id": binding["topology_node_id"],
                    })
            resources.sort(key=lambda item: (item["resource_address"], item["status"]))
            truncated = len(resources) > 2000
            safe_resources = resources[:2000]
            if drift_count and (orphan_count or missing_count):
                status = "DRIFT_ORPHAN_OR_MISSING"
            elif drift_count:
                status = "DRIFT_DETECTED"
            elif orphan_count and missing_count:
                status = "ORPHANED_AND_MISSING"
            elif orphan_count:
                status = "ORPHANED_RESOURCES"
            elif missing_count:
                status = "MISSING_RESOURCES"
            else:
                status = "CLEAN"
            details = {
                "resources": safe_resources,
                "resource_list_truncated": truncated,
                "drift_list": [
                    {"resource_address": address[:512], "resource_type": item["resource_type"], "actions": item["actions"]}
                    for address, item in sorted(drift.items())[:2000]
                ],
            }
            details_json = self._canonical(details)
            if len(details_json.encode("utf-8")) > 4 * 1024 * 1024:
                raise InfrastructureAutomationConflict("reconciliation snapshot exceeds the safe storage limit")
            now = self._now()
            refresh_hash = self._digest(plan_bytes)
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO infrastructure_reconciliations(
                        reconciliation_id,workspace_id,project_id,lab_id,status,state_sha256,
                        refresh_plan_sha256,resource_count,drift_count,orphan_count,missing_count,
                        details_json,created_at,created_by
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        reconciliation_id, workspace_id, row["project_id"], row["lab_id"], status,
                        state_sha256, refresh_hash, len(state_resources), drift_count, orphan_count,
                        missing_count, details_json, now, actor,
                    ),
                )
                self._audit(connection, actor, "INFRASTRUCTURE_RECONCILED", reconciliation_id, {
                    "workspace_id": workspace_id, "status": status,
                    "resource_count": len(state_resources), "drift_count": drift_count,
                    "orphan_count": orphan_count, "missing_count": missing_count,
                    "state_sha256": state_sha256, "refresh_plan_sha256": refresh_hash,
                })
            return self.get_reconciliation(workspace_id, reconciliation_id)
        finally:
            lease.release()

    def get_reconciliation(self, workspace_id: str, reconciliation_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT * FROM infrastructure_reconciliations
                   WHERE workspace_id=? AND reconciliation_id=?""",
                (workspace_id, reconciliation_id),
            ).fetchone()
        return self._reconciliation_view(row) if row is not None else None

    def list_reconciliations(self, workspace_id: str, *, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit), 100))
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM infrastructure_reconciliations
                   WHERE workspace_id=? ORDER BY created_at DESC,reconciliation_id DESC LIMIT ?""",
                (workspace_id, limit),
            ).fetchall()
        return [self._reconciliation_view(item) for item in rows]

    def create_recovery_plan(
        self, workspace_id: str, *, reconciliation_id: str, actor: str,
    ) -> dict:
        row = self._workspace_row(workspace_id)
        if row["status"] != "RECOVERY_REQUIRED":
            raise InfrastructureAutomationConflict("recovery planning is only valid for a RECOVERY_REQUIRED workspace")
        reconciliation = self.get_reconciliation(workspace_id, reconciliation_id)
        if reconciliation is None:
            raise InfrastructureAutomationNotFound("reconciliation snapshot was not found for this workspace")
        return self.create_plan(
            workspace_id, kind="RECOVERY", reconciliation_id=reconciliation_id, actor=actor,
        )

    def inspect(self, workspace_id: str) -> dict:
        row = self._workspace_row(workspace_id)
        workspace = self._workspace_path_for_plan_row(row)
        try:
            lease = self.resource_lock_manager.acquire_many(
                [f"lab:{row['lab_id']}", f"opentofu-workspace:{workspace_id}"],
                f"inspect:opentofu:{workspace_id}", timeout=0, lease_seconds=300,
            )
        except ResourceLockError as exc:
            raise InfrastructureAutomationConflict("Lab or OpenTofu workspace is locked; inspection was not started") from exc
        try:
            self._verify_workspace_snapshot(row, workspace)
            addresses = self.runner.state_list(workspace=workspace)
        finally:
            lease.release()
        safe = sorted({str(item)[:512] for item in addresses if isinstance(item, str) and item.strip()})[:2000]
        return {
            "workspace_id": workspace_id,
            "project_id": row["project_id"],
            "lab_id": row["lab_id"],
            "workspace_status": row["status"],
            "state_present": bool(safe),
            "resource_count": len(safe),
            "resource_addresses": safe,
            "values_exposed": False,
        }
