"""Approval-gated Ansible automation for immutable Network Intent revisions.

Only compiler-generated, hash-pinned artifacts are accepted. The service does
not accept caller-authored playbooks, arbitrary Ansible modules, shell snippets,
inventory plugins or dynamic inventory sources.
"""
from __future__ import annotations

from contextlib import ExitStack
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
import tempfile
from typing import Any, Mapping

import yaml

from lib.services.credential_vault import (
    CredentialVaultNotFound, CredentialVaultPolicyError, CredentialVaultService,
)
from lib.services.device_inventory import DeviceInventoryService
from lib.services.resource_lock import ResourceLockError, ResourceLockManager
from lib.services.network_intent_compiler import NetworkIntentCompilerService


class AnsibleAutomationError(ValueError):
    """Invalid Ansible plan, approval or execution request."""


class AnsibleAutomationNotFound(LookupError):
    """Plan, execution or managed target is outside the requested Project."""


class AnsibleAutomationConflict(AnsibleAutomationError):
    """Plan is stale, blocked, unapproved or in an invalid lifecycle state."""


@dataclass(frozen=True, slots=True)
class _CommandResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class _AnsibleCliRunner:
    """Subprocess adapter: argv only, no shell, constrained environment."""

    def __init__(self, executable: str | None = None, galaxy_executable: str | None = None):
        self.executable = executable or os.environ.get("NETREGRESS_ANSIBLE_PLAYBOOK", "ansible-playbook")
        self.galaxy_executable = galaxy_executable or os.environ.get("NETREGRESS_ANSIBLE_GALAXY", "ansible-galaxy")

    @staticmethod
    def _run(argv: list[str], *, cwd: Path, env: Mapping[str, str], timeout: int) -> _CommandResult:
        try:
            result = subprocess.run(
                argv, cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=timeout, check=False,
                shell=False,
            )
            return _CommandResult(
                int(result.returncode),
                result.stdout[-12000:],
                result.stderr[-12000:],
                False,
            )
        except FileNotFoundError:
            return _CommandResult(127, "", "ansible-playbook executable was not found", False)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
            return _CommandResult(124, stdout[-12000:], stderr[-12000:], True)

    def validate(self, *, workspace: Path, inventory: Path, playbook: Path, env: Mapping[str, str]) -> dict:
        version = self._run(
            [self.executable, "--version"], cwd=workspace, env=env, timeout=30,
        )
        if version.exit_code != 0:
            return {"valid": False, "code": "ANSIBLE_EXECUTABLE_UNAVAILABLE", "message": "ansible-playbook is unavailable"}
        match = re.search(r"ansible(?:-playbook)?\s+\[?core\s+([0-9]+\.[0-9]+\.[0-9]+)", version.stdout + version.stderr, re.I)
        if not match:
            match = re.search(r"ansible\s+([0-9]+\.[0-9]+\.[0-9]+)", version.stdout + version.stderr, re.I)
        if not match or not match.group(1).startswith("2.21."):
            return {
                "valid": False, "code": "ANSIBLE_VERSION_UNSUPPORTED",
                "message": "Ansible Core 2.21.x is required for the pinned P10 collections",
            }
        collection_result = self._run(
            [self.galaxy_executable, "collection", "list"],
            cwd=workspace, env=env, timeout=60,
        )
        expected_collections = {
            "ansible.netcommon": "8.7.1",
            "cisco.ios": "11.6.0",
            "arista.eos": "12.3.0",
        }
        discovered = {}
        for line in (collection_result.stdout + "\n" + collection_result.stderr).splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] in expected_collections:
                discovered[parts[0]] = parts[1]
        missing = [
            name for name, version_value in expected_collections.items()
            if discovered.get(name) != version_value
        ]
        if collection_result.exit_code != 0 or missing:
            return {
                "valid": False, "code": "ANSIBLE_COLLECTIONS_MISSING_OR_UNPINNED",
                "message": "Install the exact P10 Ansible collections before creating an executable plan: "
                           + ", ".join(f"{name}=={expected_collections[name]}" for name in missing),
                "ansible_core": match.group(1),
            }
        checks = ["PINNED_COLLECTIONS_PASSED"]
        for label, arguments in (
            ("syntax", ["--syntax-check"]),
            ("inventory", ["--list-hosts"]),
        ):
            result = self._run(
                [self.executable, "-i", str(inventory), *arguments, str(playbook)],
                cwd=workspace, env=env, timeout=120,
            )
            if result.exit_code != 0:
                return {
                    "valid": False,
                    "code": "ANSIBLE_PLAYBOOK_SYNTAX_FAILED" if label == "syntax" else "ANSIBLE_INVENTORY_VALIDATION_FAILED",
                    "message": f"Ansible {label} validation failed",
                    "detail": (result.stderr or result.stdout)[-3000:],
                    "ansible_core": match.group(1),
                }
            checks.append(label.upper() + "_CHECK_PASSED")
        return {
            "valid": True, "code": "ANSIBLE_PLAYBOOK_VALIDATED",
            "message": "Playbook syntax and static inventory checks passed",
            "ansible_core": match.group(1), "checks": checks,
        }

    def execute(
        self, *, workspace: Path, inventory: Path, playbook: Path,
        env: Mapping[str, str], timeout_seconds: int,
    ) -> _CommandResult:
        return self._run(
            [
                self.executable, "-i", str(inventory), str(playbook),
                "--diff", "--forks", "1", "--timeout", "25", "--force-handlers",
            ],
            cwd=workspace, env=env, timeout=timeout_seconds,
        )


class AnsibleAutomationService:
    """Create, validate, approve and execute scoped Ansible automation plans."""

    SCHEMA_VERSION = "1.0"
    MAX_PLAN_BYTES = 5_000_000
    MAX_PLAYBOOK_BYTES = 1_000_000
    EXECUTION_TIMEOUT_SECONDS = 1800
    SUPPORTED_ADAPTERS = {
        "linux_frr": {
            "platform": "Linux/FRR",
            "connection": "ssh",
            "network_os": None,
        },
        "cisco_iosxe": {
            "platform": "Cisco IOS/IOS-XE",
            "connection": "ansible.netcommon.network_cli",
            "network_os": "cisco.ios.ios",
        },
        "arista_eos": {
            "platform": "Arista EOS",
            "connection": "ansible.netcommon.network_cli",
            "network_os": "arista.eos.eos",
        },
    }

    def __init__(
        self,
        database,
        network_intent,
        compiler: NetworkIntentCompilerService,
        device_inventory: DeviceInventoryService,
        credential_vault: CredentialVaultService,
        *,
        runner=None,
        resource_lock_manager: ResourceLockManager | None = None,
    ) -> None:
        self.database = database
        self.network_intent = network_intent
        self.compiler = compiler
        self.devices = device_inventory
        self.vault = credential_vault
        self.runner = runner or _AnsibleCliRunner()
        self.resource_lock_manager = resource_lock_manager or ResourceLockManager(
            Path(database.path).resolve().parent / "locks"
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise AnsibleAutomationError("actor must contain 1 to 128 printable characters")
        return actor

    @staticmethod
    def _canonical(value: object) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise AnsibleAutomationError("Ansible plan must contain finite JSON-compatible values") from exc

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(AnsibleAutomationService._canonical(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_summary(value: object, *, secrets_to_redact: tuple[str, ...] = ()) -> str:
        text = str(value or "")
        for secret in secrets_to_redact:
            if secret:
                text = text.replace(secret, "[redacted]")
        text = re.sub(
            r"(?i)(password|passwd|secret|token|private[-_ ]key|api[-_ ]key)(\s*[=:]\s*)[^\s,;]+",
            r"\1\2[redacted]", text,
        )
        return text[-6000:]

    @staticmethod
    def _safe_alias(device_id: str) -> str:
        return "nr_" + hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _artifact_basename(path: str) -> str:
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
            raise AnsibleAutomationError("compiler artifact path is not a confined relative path")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", parsed.name):
            raise AnsibleAutomationError("compiler artifact basename contains unsupported characters")
        return parsed.name

    @staticmethod
    def _readback_anchor(adapter_id: str, content: str) -> str:
        patterns = {
            "cisco_iosxe": r"(?m)^hostname\s+[^\r\n]+",
            "arista_eos": r"(?m)^hostname\s+[^\r\n]+",
            "juniper_junos": r"(?m)^set system host-name\s+[^\r\n]+",
        }
        match = re.search(patterns[adapter_id], content)
        if not match:
            raise AnsibleAutomationError("compiled configuration has no safe read-back anchor")
        return match.group(0).strip()

    @staticmethod
    def _network_config_text(adapter_id: str, content: str) -> str:
        # cli_config enters configuration mode itself; terminal mode commands
        # must not be submitted as configuration lines.
        if adapter_id in {"cisco_iosxe", "arista_eos"}:
            lines = [line for line in content.splitlines() if line.strip().lower() != "end"]
            return "\n".join(lines).rstrip() + "\n"
        return content.rstrip() + "\n"

    @staticmethod
    def _linux_destination(relative_path: str) -> str:
        path = PurePosixPath(relative_path)
        if path.parts[:2] == ("systemd", "network"):
            return "/etc/systemd/network/" + AnsibleAutomationService._artifact_basename(relative_path)
        if path.parts == ("frr", "frr.conf"):
            return "/etc/frr/frr.conf"
        if path.parts == ("nftables", "netregress.nft"):
            return "/etc/nftables.d/netregress.nft"
        if path.parts == ("operator", "link-state.sh"):
            return "/usr/local/sbin/netregress-link-state.sh"
        raise AnsibleAutomationError("Linux adapter returned an artifact outside the approved deployment paths")

    def _build_playbook(self, compilation: dict, target_devices: list[dict]) -> tuple[dict, dict]:
        artifacts_by_device: dict[str, list[dict]] = {}
        for artifact in compilation["artifacts"]:
            match = re.fullmatch(r"targets/[^/]+-(dev_[A-Za-z0-9]+)/(.*)", artifact["path"])
            if not match:
                raise AnsibleAutomationError("compiler artifact path cannot be mapped to a managed Device")
            device_id = match.group(1)
            artifacts_by_device.setdefault(device_id, []).append({
                **artifact, "relative_path": match.group(2),
            })

        hosts: dict[str, dict] = {}
        plays: list[dict] = []
        targets: list[dict] = []
        for target in target_devices:
            device_id = target["device_id"]
            adapter_id = target["adapter_id"]
            adapter = self.SUPPORTED_ADAPTERS.get(adapter_id)
            if adapter is None:
                raise AnsibleAutomationConflict(
                    f"Ansible P10 does not yet provide a validated execution transport for {adapter_id}; no plan was created"
                )
            artifacts = artifacts_by_device.get(device_id, [])
            if not artifacts:
                raise AnsibleAutomationError("compiler output contains no artifact for a mapped Device")
            alias = self._safe_alias(device_id)
            host_vars: dict[str, Any] = {
                "ansible_host": target["host"],
                "ansible_port": int(target["port"]),
                "ansible_user": target["username"],
                "ansible_connection": adapter["connection"],
                "ansible_connect_timeout": 30,
                "ansible_command_timeout": 180,
            }
            if adapter["network_os"]:
                host_vars["ansible_network_os"] = adapter["network_os"]
                host_vars["ansible_persistent_command_timeout"] = 180
                host_vars["ansible_persistent_connect_timeout"] = 30
            hosts[alias] = host_vars
            play = {
                "name": f"NetRegress approved configuration deployment · {device_id}",
                "hosts": alias,
                "gather_facts": False,
                "serial": 1,
                "any_errors_fatal": True,
                "tasks": [],
            }
            if adapter_id == "linux_frr" and str(target["username"]).casefold() != "root":
                play.update({"become": True, "become_method": "sudo", "become_flags": "-n"})
            tasks = play["tasks"]
            if adapter_id == "linux_frr":
                destinations = []
                for artifact in artifacts:
                    destination = self._linux_destination(artifact["relative_path"])
                    directory = str(PurePosixPath(destination).parent)
                    tasks.append({
                        "name": "Create approved configuration directory",
                        "ansible.builtin.file": {
                            "path": directory, "state": "directory", "owner": "root", "group": "root", "mode": "0755",
                        },
                    })
                    tasks.append({
                        "name": "Install hash-pinned compiled Linux configuration",
                        "ansible.builtin.copy": {
                            "content": artifact["content"], "dest": destination,
                            "owner": "root", "group": "root",
                            "mode": "0700" if destination.endswith(".sh") else "0644",
                            "backup": True,
                        },
                        "no_log": True,
                    })
                    destinations.append({"path": destination, "sha256": artifact["sha256"]})
                nft = next((item for item in destinations if item["path"] == "/etc/nftables.d/netregress.nft"), None)
                if nft:
                    tasks.append({
                        "name": "Validate nftables configuration before activation",
                        "ansible.builtin.command": {
                            "argv": ["/usr/sbin/nft", "-c", "-f", nft["path"]],
                        },
                        "changed_when": False,
                        "no_log": True,
                    })
                if any(item["path"].startswith("/etc/systemd/network/") for item in destinations):
                    tasks.extend([
                        {"name": "Reload systemd unit metadata", "ansible.builtin.systemd": {"daemon_reload": True}},
                        {"name": "Apply systemd-networkd configuration", "ansible.builtin.systemd": {"name": "systemd-networkd", "state": "restarted"}, "no_log": True},
                    ])
                if any(item["path"] == "/etc/frr/frr.conf" for item in destinations):
                    tasks.append({
                        "name": "Apply FRRouting configuration",
                        "ansible.builtin.systemd": {"name": "frr", "state": "restarted"},
                        "no_log": True,
                    })
                if nft:
                    tasks.append({
                        "name": "Apply nftables policy",
                        "ansible.builtin.command": {"argv": ["/usr/sbin/nft", "-f", nft["path"]]},
                        "no_log": True,
                    })
                script = next((item for item in destinations if item["path"] == "/usr/local/sbin/netregress-link-state.sh"), None)
                if script:
                    tasks.append({
                        "name": "Apply reviewed Linux link state",
                        "ansible.builtin.command": {"argv": [script["path"]]},
                        "no_log": True,
                    })
                for index, item in enumerate(destinations):
                    tasks.append({
                        "name": f"Read back deployed artifact {index + 1}",
                        "ansible.builtin.stat": {
                            "path": item["path"], "checksum_algorithm": "sha256",
                        },
                        "register": f"netregress_artifact_{index}",
                        "no_log": True,
                    })
                    tasks.append({
                        "name": f"Verify artifact checksum {index + 1}",
                        "ansible.builtin.assert": {
                            "that": [f"netregress_artifact_{index}.stat.checksum == '{item['sha256']}'"],
                            "fail_msg": "Deployed configuration read-back checksum did not match",
                        },
                        "no_log": True,
                    })
                readback_method = "remote SHA-256 checksum of every installed file"
            else:
                primary = next((item for item in artifacts if item["relative_path"].endswith(".txt") or item["relative_path"].endswith(".set")), artifacts[0])
                readback = (
                    "show configuration | display set"
                    if adapter_id == "juniper_junos" else "show running-config"
                )
                anchor = self._readback_anchor(adapter_id, primary["content"])
                config_text = self._network_config_text(adapter_id, primary["content"])
                tasks.extend([
                    {
                        "name": "Apply hash-pinned vendor configuration using network_cli",
                        "ansible.netcommon.cli_config": {
                            "config": config_text,
                            "backup": True,
                            "commit": True,
                        },
                        "no_log": True,
                    },
                    {
                        "name": "Read back live vendor configuration",
                        "ansible.netcommon.cli_command": {"command": readback},
                        "register": "netregress_running_config",
                        "no_log": True,
                    },
                    {
                        "name": "Verify expected configuration anchor in read-back",
                        "ansible.builtin.assert": {
                            "that": [f"{json.dumps(anchor)} in netregress_running_config.stdout"],
                            "fail_msg": "Device read-back did not contain the expected configuration anchor",
                        },
                        "no_log": True,
                    },
                ])
                readback_method = "live show configuration output contains the compiled hostname anchor"
            tasks.append({
                "name": "Record verified device read-back evidence",
                "ansible.builtin.copy": {
                    "content": json.dumps({
                        "device_id": device_id, "adapter_id": adapter_id,
                        "verified": True, "readback_method": readback_method,
                        "intent_sha256": compilation["intent_sha256"],
                    }, sort_keys=True, separators=(",", ":")),
                    "dest": "{{ lookup('ansible.builtin.env', 'NETREGRESS_ANSIBLE_EVIDENCE_DIR') }}/" + alias + ".json",
                    "mode": "0600",
                },
                "delegate_to": "localhost",
                "no_log": True,
            })
            plays.append(play)
            targets.append({
                "device_id": device_id, "lab_id": target["lab_id"], "device_key": target["device_key"],
                "name": target["name"], "host": target["host"], "port": target["port"],
                "vendor": target["vendor"], "model": target["model"],
                "adapter_id": adapter_id, "credential_id": target["credential_id"],
                "credential_type": target["credential_type"], "inventory_alias": alias,
                "artifact_paths": [item["path"] for item in artifacts],
                "readback_method": readback_method,
            })
        inventory = {
            "all": {
                "children": {
                    "netregress_targets": {
                        "hosts": hosts,
                    },
                },
            },
        }
        playbook = {
            "name": "NetRegress immutable Network Intent deployment",
            "hosts": "netregress_targets",
            "gather_facts": False,
        }
        return {"plays": plays, "targets": targets}, inventory

    def _workspace(self, plan: dict, *, secrets_by_device: Mapping[str, tuple[dict, str]] | None = None) -> tuple[tempfile.TemporaryDirectory, Path, Path, dict[str, str]]:
        workspace = tempfile.TemporaryDirectory(prefix="netregress-ansible-")
        root = Path(workspace.name).resolve()
        root.chmod(0o700)
        (root / "local_tmp").mkdir(mode=0o700)
        (root / "evidence").mkdir(mode=0o700)
        playbook_path = root / "playbook.yml"
        inventory_path = root / "inventory.yml"
        config_path = root / "ansible.cfg"
        playbook_path.write_text(plan["playbook_yaml"], encoding="utf-8")
        inventory = json.loads(json.dumps(plan["inventory"]))
        hosts = inventory["all"]["children"]["netregress_targets"]["hosts"]
        for target in plan["targets"]:
            if secrets_by_device and target["device_id"] in secrets_by_device:
                record, secret = secrets_by_device[target["device_id"]]
                host = hosts[target["inventory_alias"]]
                if record["credential_type"] == "SSH_PASSWORD":
                    host["ansible_password"] = secret
                elif record["credential_type"] == "SSH_PRIVATE_KEY":
                    key_path = root / (target["inventory_alias"] + ".key")
                    key_path.write_text(secret, encoding="utf-8")
                    key_path.chmod(0o600)
                    host["ansible_ssh_private_key_file"] = str(key_path)
                else:
                    workspace.cleanup()
                    raise AnsibleAutomationConflict("only SSH_PASSWORD and SSH_PRIVATE_KEY credentials can be supplied to P10")
        inventory_path.write_text(yaml.safe_dump(inventory, sort_keys=False), encoding="utf-8")
        config_path.write_text(
            "[defaults]\n"
            "host_key_checking = True\n"
            "retry_files_enabled = False\n"
            "interpreter_python = auto_silent\n"
            "forks = 1\n"
            "timeout = 25\n"
            "local_tmp = ./local_tmp\n"
            "display_args_to_stdout = False\n"
            "stdout_callback = default\n"
            "[ssh_connection]\n"
            "pipelining = True\n",
            encoding="utf-8",
        )
        for path in (playbook_path, inventory_path, config_path):
            path.chmod(0o600)
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(Path.home()),
            "ANSIBLE_CONFIG": str(config_path),
            "ANSIBLE_HOST_KEY_CHECKING": "True",
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_RETRY_FILES_ENABLED": "False",
            "ANSIBLE_LOCAL_TEMP": str(root / "local_tmp"),
            "ANSIBLE_SSH_CONTROL_PATH_DIR": str(root / "local_tmp"),
            "ANSIBLE_REMOTE_TEMP": "/tmp/.ansible/tmp",
            "NETREGRESS_ANSIBLE_EVIDENCE_DIR": str(root / "evidence"),
            "PYTHONNOUSERSITE": "1",
        }
        return workspace, inventory_path, playbook_path, env

    @staticmethod
    def _runner_summary(result: object) -> dict:
        if isinstance(result, Mapping):
            return {
                "exit_code": int(result.get("exit_code", 1)),
                "stdout": str(result.get("stdout", "")),
                "stderr": str(result.get("stderr", "")),
                "timed_out": bool(result.get("timed_out", False)),
            }
        return {
            "exit_code": int(getattr(result, "exit_code", 1)),
            "stdout": str(getattr(result, "stdout", "")),
            "stderr": str(getattr(result, "stderr", "")),
            "timed_out": bool(getattr(result, "timed_out", False)),
        }

    def _validate_workspace(self, plan: dict) -> dict:
        workspace, inventory, playbook, env = self._workspace(plan)
        try:
            result = self.runner.validate(
                workspace=Path(workspace.name), inventory=inventory,
                playbook=playbook, env=env,
            )
            if not isinstance(result, Mapping):
                raise AnsibleAutomationError("Ansible validation runner returned an invalid result")
            return dict(result)
        except Exception as exc:
            return {
                "valid": False, "code": "ANSIBLE_VALIDATION_FAILED",
                "message": f"Ansible validation could not complete ({type(exc).__name__})",
            }
        finally:
            workspace.cleanup()

    def create_plan(
        self,
        profile_id: str,
        revision_id: str,
        *,
        credential_bindings: Mapping[str, str],
        actor: str,
    ) -> dict:
        actor = self._actor(actor)
        profile = self.network_intent.get_profile(profile_id)
        revision = self.network_intent.get_revision(revision_id)
        if profile is None or revision is None or revision["profile_id"] != profile_id:
            raise AnsibleAutomationNotFound("Network Intent profile or revision not found")
        if profile["status"] != "ACTIVE" or revision["status"] != "PUBLISHED":
            raise AnsibleAutomationConflict("Ansible plans require an active profile and immutable PUBLISHED Network Intent revision")
        if not isinstance(credential_bindings, Mapping) or not credential_bindings:
            raise AnsibleAutomationError("credential_bindings must map each target Device ID to an active SSH credential ID")
        compilation = self.compiler.compile_revision(profile_id, revision_id)
        if compilation.get("status") != "COMPILED":
            return {
                "status": "BLOCKED", "plan_id": None, "profile_id": profile_id,
                "revision_id": revision_id, "diagnostics": compilation.get("diagnostics", []),
            }
        definition = revision["definition"]
        target_bindings = {item["device_id"] for item in definition.get("targets", [])}
        if set(credential_bindings) != target_bindings:
            raise AnsibleAutomationError("credential_bindings must contain exactly one credential ID for every target Device")
        target_devices = []
        for target in definition.get("targets", []):
            device = self.devices.get(target["device_id"])
            if device is None or device["project_id"] != profile["project_id"] or device["status"] != "ACTIVE":
                raise AnsibleAutomationNotFound("one or more target Devices are missing or outside this Project")
            if profile["lab_id"] and device["lab_id"] != profile["lab_id"]:
                raise AnsibleAutomationConflict("every target Device must belong to the Network Intent Lab scope")
            credential_id = str(credential_bindings[target["device_id"]] or "").strip()
            credential = self.vault.get(credential_id) if credential_id else None
            if (
                credential is None or credential["project_id"] != profile["project_id"]
                or credential["device_id"] != target["device_id"] or credential["status"] != "ACTIVE"
                or credential["credential_type"] not in {"SSH_PASSWORD", "SSH_PRIVATE_KEY"}
                or not credential.get("username")
            ):
                raise AnsibleAutomationConflict("each target needs an active same-Device SSH_PASSWORD or SSH_PRIVATE_KEY vault credential with a username")
            reports = self.network_intent.list_capability_reports(
                profile["project_id"], device_id=target["device_id"],
            )
            if not reports:
                raise AnsibleAutomationConflict("a fresh observed capability report is required before Ansible plan creation")
            adapter = self.compiler.registry.resolve(device, reports[0])
            adapter_id = adapter.descriptor.adapter_id
            if adapter_id not in self.SUPPORTED_ADAPTERS:
                raise AnsibleAutomationConflict(
                    f"Ansible P10 does not yet provide a validated execution transport for {adapter_id}"
                )
            target_devices.append({
                "device_id": device["device_id"],
                "lab_id": device["lab_id"],
                "device_key": device["device_key"],
                "name": device["name"],
                "host": device["host"],
                "port": int(device["port"]),
                "vendor": device["vendor"],
                "model": device["model"],
                "username": credential["username"],
                "credential_id": credential_id,
                "credential_type": credential["credential_type"],
                "adapter_id": adapter_id,
            })
        playbook_data, inventory = self._build_playbook(compilation, target_devices)
        playbook_yaml = yaml.safe_dump(playbook_data["plays"], sort_keys=False, allow_unicode=True)
        if len(playbook_yaml.encode("utf-8")) > self.MAX_PLAYBOOK_BYTES:
            raise AnsibleAutomationError("generated Ansible playbook exceeds the one-megabyte limit")
        # The inventory preview deliberately excludes passwords and private keys.
        plan_body = {
            "schema_version": self.SCHEMA_VERSION,
            "project_id": profile["project_id"],
            "lab_id": profile["lab_id"],
            "profile_id": profile_id,
            "revision_id": revision_id,
            "intent_sha256": revision["intent_sha256"],
            "topology_content_sha256": revision["topology_content_sha256"],
            "compiler_version": compilation["compiler_version"],
            "compilation_id": compilation["compilation_id"],
            "adapters": compilation["adapters"],
            "targets": playbook_data["targets"],
            "artifacts": [
                {key: item[key] for key in ("path", "sha256", "content", "change_type")}
                for item in compilation["artifacts"]
            ],
            "playbook_yaml": playbook_yaml,
            "playbook_sha256": hashlib.sha256(playbook_yaml.encode("utf-8")).hexdigest(),
            "inventory": inventory,
            "preview_contract": {
                "syntax_check": "ansible-playbook --syntax-check",
                "inventory_check": "ansible-playbook --list-hosts",
                "device_connection": False,
                "configuration_apply": False,
                "approval_required": True,
            },
        }
        encoded = self._canonical(plan_body)
        if len(encoded.encode("utf-8")) > self.MAX_PLAN_BYTES:
            raise AnsibleAutomationError("Ansible plan exceeds the five-megabyte persistence limit")
        plan_sha256 = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        plan_id = "nap_" + secrets.token_hex(12)
        validation = self._validate_workspace({**plan_body, "plan_sha256": plan_sha256})
        status = "PREVIEWED" if validation.get("valid") is True else "BLOCKED"
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO ansible_automation_plans(
                   plan_id,project_id,lab_id,profile_id,revision_id,plan_sha256,plan_json,
                   validation_json,status,created_at,updated_at,created_by,approved_at,approved_by
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)""",
                (plan_id, profile["project_id"], profile["lab_id"], profile_id, revision_id,
                 plan_sha256, encoded, self._canonical(validation), status, now, now, actor),
            )
            self._audit(
                connection, actor, "ANSIBLE_AUTOMATION_PLAN_CREATED", plan_id,
                {"resource_type": "ANSIBLE_AUTOMATION_PLAN", "project_id": profile["project_id"], "lab_id": profile["lab_id"],
                 "profile_id": profile_id, "revision_id": revision_id,
                 "plan_sha256": plan_sha256, "status": status},
            )
        return self.get_plan(plan_id) or {}

    @staticmethod
    def _audit(connection, actor: str, action: str, resource_id: str, details: dict) -> None:
        connection.execute(
            """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("AUD-" + secrets.token_hex(12), actor, action, "ANSIBLE_AUTOMATION", resource_id,
             AnsibleAutomationService._canonical(details), AnsibleAutomationService._now()),
        )

    def _decode_plan(self, row) -> dict:
        if row is None:
            return None
        plan = json.loads(row["plan_json"])
        encoded = self._canonical(plan)
        if hashlib.sha256(encoded.encode("utf-8")).hexdigest() != row["plan_sha256"]:
            raise AnsibleAutomationError("stored Ansible plan failed its SHA-256 integrity check")
        playbook_text = plan.get("playbook_yaml")
        playbook_hash = plan.get("playbook_sha256")
        if not isinstance(playbook_text, str) or hashlib.sha256(playbook_text.encode("utf-8")).hexdigest() != playbook_hash:
            raise AnsibleAutomationError("stored Ansible playbook failed its SHA-256 integrity check")
        for artifact in plan.get("artifacts", []):
            content = artifact.get("content")
            digest = artifact.get("sha256")
            if not isinstance(content, str) or hashlib.sha256(content.encode("utf-8")).hexdigest() != digest:
                raise AnsibleAutomationError("stored compiler artifact failed its SHA-256 integrity check")
        result = {
            key: row[key] for key in (
                "plan_id", "project_id", "lab_id", "profile_id", "revision_id", "plan_sha256",
                "status", "created_at", "updated_at", "created_by", "approved_at", "approved_by",
            )
        }
        result["plan"] = plan
        result["validation"] = json.loads(row["validation_json"])
        result["approvals"] = self.list_approvals(row["plan_id"])
        result["executions"] = self.list_executions(row["plan_id"])
        return result

    def get_plan(self, plan_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM ansible_automation_plans WHERE plan_id=?", (plan_id,)).fetchone()
        return self._decode_plan(row)

    def list_plans(self, project_id: str, *, limit: int = 25) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise AnsibleAutomationError("limit must be an integer")
        limit = max(1, min(limit, 100))
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT plan_id FROM ansible_automation_plans WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        return [self.get_plan(row["plan_id"]) for row in rows]

    def list_approvals(self, plan_id: str) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT approval_id,plan_id,plan_sha256,approved_by,confirmed_at FROM ansible_automation_approvals WHERE plan_id=? ORDER BY confirmed_at",
                (plan_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_executions(self, plan_id: str) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT execution_id,plan_id,approval_id,plan_sha256,status,result_json,started_at,completed_at,executed_by FROM ansible_automation_executions WHERE plan_id=? ORDER BY started_at DESC",
                (plan_id,),
            ).fetchall()
        return [
            {key: row[key] for key in ("execution_id", "plan_id", "approval_id", "plan_sha256", "status", "started_at", "completed_at", "executed_by")}
            | {"result": json.loads(row["result_json"])}
            for row in rows
        ]

    def approve(self, plan_id: str, *, expected_plan_sha256: str, confirmed: bool, actor: str) -> dict:
        actor = self._actor(actor)
        if confirmed is not True:
            raise AnsibleAutomationConflict("explicit approval confirmation is required")
        plan = self.get_plan(plan_id)
        if plan is None:
            raise AnsibleAutomationNotFound("Ansible automation plan not found")
        if plan["status"] != "PREVIEWED":
            raise AnsibleAutomationConflict("only a validated PREVIEWED Ansible plan may be approved")
        if expected_plan_sha256 != plan["plan_sha256"]:
            raise AnsibleAutomationConflict("plan hash changed; create and review a fresh plan before approval")
        if plan["created_by"] == actor:
            raise AnsibleAutomationConflict("the plan creator cannot approve their own deployment plan; an independent ADMIN or OWNER must approve it")
        approval_id = "naa_" + secrets.token_hex(12)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO ansible_automation_approvals(
                   approval_id,plan_id,plan_sha256,approved_by,confirmed_at
                   ) VALUES(?,?,?,?,?)""",
                (approval_id, plan_id, expected_plan_sha256, actor, now),
            )
            cursor = connection.execute(
                """UPDATE ansible_automation_plans SET status='APPROVED',updated_at=?,approved_at=?,approved_by=?
                   WHERE plan_id=? AND status='PREVIEWED' AND plan_sha256=?""",
                (now, now, actor, plan_id, expected_plan_sha256),
            )
            if cursor.rowcount != 1:
                raise AnsibleAutomationConflict("plan changed during approval")
            self._audit(
                connection, actor, "ANSIBLE_AUTOMATION_PLAN_APPROVED", plan_id,
                {"approval_id": approval_id, "plan_sha256": expected_plan_sha256},
            )
        return self.get_plan(plan_id) or {}

    def _with_vault_secrets(
        self, plan: dict, actor: str, index: int,
        resolved: dict[str, tuple[dict, str]], callback,
    ):
        targets = plan["plan"]["targets"]
        if index >= len(targets):
            return callback(resolved)
        target = targets[index]
        device_id = target["device_id"]
        credential_id = target["credential_id"]
        return self.vault.use_secret(
            credential_id,
            project_id=plan["project_id"],
            device_id=device_id,
            credential_type=target["credential_type"],
            actor=actor,
            purpose="ansible_automation",
            consumer=lambda record, secret: self._with_vault_secrets(
                plan, actor, index + 1,
                resolved | {device_id: (dict(record), secret)}, callback,
            ),
        )

    def _finish_execution(
        self, execution_id: str, plan_id: str, *,
        status: str, result: dict, actor: str,
    ) -> dict:
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE ansible_automation_executions
                   SET status=?,result_json=?,completed_at=?
                   WHERE execution_id=? AND status='RUNNING'""",
                (status, self._canonical(result), now, execution_id),
            )
            if cursor.rowcount != 1:
                raise AnsibleAutomationConflict("Ansible execution evidence changed before completion")
            connection.execute(
                "UPDATE ansible_automation_plans SET status=?,updated_at=? WHERE plan_id=? AND status='EXECUTING'",
                ("SUCCEEDED" if status == "SUCCEEDED" else "FAILED", now, plan_id),
            )
            self._audit(
                connection, actor, "ANSIBLE_AUTOMATION_EXECUTION_" + status,
                execution_id, {"plan_id": plan_id, "status": status},
            )
            row = connection.execute(
                "SELECT * FROM ansible_automation_executions WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
        return {
            key: row[key] for key in (
                "execution_id", "plan_id", "approval_id", "plan_sha256",
                "status", "started_at", "completed_at", "executed_by",
            )
        } | {"result": json.loads(row["result_json"])}

    def execute(
        self,
        plan_id: str,
        *,
        expected_plan_sha256: str,
        confirmed: bool,
        actor: str,
    ) -> dict:
        actor = self._actor(actor)
        if confirmed is not True:
            raise AnsibleAutomationConflict("explicit execution confirmation is required")
        plan = self.get_plan(plan_id)
        if plan is None:
            raise AnsibleAutomationNotFound("Ansible automation plan not found")
        if plan["status"] != "APPROVED":
            raise AnsibleAutomationConflict("Ansible plan must be approved before execution")
        if expected_plan_sha256 != plan["plan_sha256"]:
            raise AnsibleAutomationConflict("approved plan hash does not match the requested execution")
        if plan["validation"].get("valid") is not True:
            raise AnsibleAutomationConflict("Ansible syntax and static inventory checks must pass before execution")
        approvals = [item for item in plan["approvals"] if item["plan_sha256"] == expected_plan_sha256]
        if not approvals:
            raise AnsibleAutomationConflict("a matching immutable approval record is required")
        approval = approvals[-1]
        plan_data = plan["plan"]
        leases = None
        execution_id = "nae_" + secrets.token_hex(12)
        now = self._now()
        try:
            leases = self.resource_lock_manager.acquire_many(
                [*[f"lab:{item['lab_id']}" for item in plan_data["targets"]], *[f"device:{item['device_id']}" for item in plan_data["targets"]]],
                "ansible-automation:" + actor[:80], timeout=0.0, lease_seconds=self.EXECUTION_TIMEOUT_SECONDS + 120,
            )
        except (ResourceLockError, OSError, ValueError) as exc:
            raise AnsibleAutomationConflict("Lab or Device is locked by another operation; no Ansible connection was opened") from exc
        def revalidate_after_approval() -> None:
            try:
                latest_compilation = self.compiler.compile_revision(
                    plan["profile_id"], plan["revision_id"],
                )
            except Exception:
                latest_compilation = {"status": "BLOCKED"}
            if (
                latest_compilation.get("status") != "COMPILED"
                or latest_compilation.get("compilation_id") != plan_data.get("compilation_id")
                or latest_compilation.get("intent_sha256") != plan_data.get("intent_sha256")
                or latest_compilation.get("topology_content_sha256") != plan_data.get("topology_content_sha256")
            ):
                stale_at = self._now()
                with self.database.transaction(immediate=True) as connection:
                    cursor = connection.execute(
                        """UPDATE ansible_automation_plans SET status='STALE',updated_at=?
                           WHERE plan_id=? AND status='APPROVED' AND plan_sha256=?""",
                        (stale_at, plan_id, expected_plan_sha256),
                    )
                    if cursor.rowcount == 1:
                        self._audit(
                            connection, actor, "ANSIBLE_AUTOMATION_PLAN_STALE", plan_id,
                            {"plan_sha256": expected_plan_sha256,
                             "reason": "source intent, topology, observed capabilities or compiled output changed"},
                        )
                raise AnsibleAutomationConflict(
                    "Network Intent, target capabilities or compiled artifacts changed after approval; "
                    "plan is now STALE and must be recreated and independently approved"
                )

        try:
            revalidate_after_approval()
            with self.database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    """UPDATE ansible_automation_plans SET status='EXECUTING',updated_at=?
                       WHERE plan_id=? AND status='APPROVED' AND plan_sha256=?""",
                    (now, plan_id, expected_plan_sha256),
                )
                if cursor.rowcount != 1:
                    raise AnsibleAutomationConflict("plan changed before execution")
                connection.execute(
                    """INSERT INTO ansible_automation_executions(
                       execution_id,plan_id,approval_id,plan_sha256,status,result_json,
                       started_at,completed_at,executed_by
                       ) VALUES(?,?,?,?, 'RUNNING','{}',?,NULL,?)""",
                    (execution_id, plan_id, approval["approval_id"], expected_plan_sha256, now, actor),
                )
                self._audit(
                    connection, actor, "ANSIBLE_AUTOMATION_EXECUTION_STARTED",
                    execution_id, {"plan_id": plan_id, "approval_id": approval["approval_id"],
                                   "plan_sha256": expected_plan_sha256, "target_count": len(plan_data["targets"])},
                )

            def run_with_secrets(secrets_by_device):
                workspace, inventory, playbook, env = self._workspace(plan_data, secrets_by_device=secrets_by_device)
                try:
                    result = self._runner_summary(self.runner.execute(
                        workspace=Path(workspace.name), inventory=inventory,
                        playbook=playbook, env=env, timeout_seconds=self.EXECUTION_TIMEOUT_SECONDS,
                    ))
                    evidence_dir = Path(workspace.name) / "evidence"
                    verified = []
                    for target in plan_data["targets"]:
                        evidence_file = evidence_dir / (target["inventory_alias"] + ".json")
                        if evidence_file.is_file():
                            try:
                                evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
                            except (OSError, json.JSONDecodeError):
                                evidence = {}
                            if evidence.get("verified") is True and evidence.get("device_id") == target["device_id"]:
                                verified.append(target["device_id"])
                    secrets_to_redact = tuple(secret for _record, secret in secrets_by_device.values())
                    summary = {
                        "ansible_exit_code": result["exit_code"],
                        "timed_out": result["timed_out"],
                        "targets": [
                            {
                                "device_id": item["device_id"],
                                "adapter_id": item["adapter_id"],
                                "readback_status": "VERIFIED" if item["device_id"] in verified else "NOT_VERIFIED",
                                "readback_method": item["readback_method"],
                            } for item in plan_data["targets"]
                        ],
                        "verified_device_count": len(verified),
                        "target_count": len(plan_data["targets"]),
                        "partial_changes_possible": result["exit_code"] != 0,
                        "diagnostic": self._safe_summary(
                            result["stderr"] or result["stdout"], secrets_to_redact=secrets_to_redact,
                        ),
                    }
                    success = result["exit_code"] == 0 and len(verified) == len(plan_data["targets"])
                    return success, summary
                finally:
                    workspace.cleanup()

            success, summary = self._with_vault_secrets(plan, actor, 0, {}, run_with_secrets)
            return self._finish_execution(
                execution_id, plan_id,
                status="SUCCEEDED" if success else "FAILED",
                result={
                    **summary,
                    "application_performed": True,
                    "readback_status": "VERIFIED" if success else "INCOMPLETE",
                    "rollback_performed": False,
                    "reconciliation_required": not success,
                },
                actor=actor,
            )
        except Exception as exc:
            # The adapter may have changed an earlier target before a later
            # host failed. Persist an explicit uncertain/partial state; never
            # retry automatically or claim the operation was atomic.
            try:
                current = self.get_plan(plan_id)
                latest = current["executions"][0] if current and current["executions"] else None
                if latest and latest["execution_id"] == execution_id and latest["status"] == "RUNNING":
                    return self._finish_execution(
                        execution_id, plan_id, status="FAILED",
                        result={
                            "error_type": type(exc).__name__,
                            "message": "Ansible execution did not complete; some earlier target changes may have succeeded",
                            "application_performed": True,
                            "partial_changes_possible": True,
                            "readback_status": "INCOMPLETE",
                            "reconciliation_required": True,
                        },
                        actor=actor,
                    )
            except Exception:
                pass
            if isinstance(exc, (AnsibleAutomationError, AnsibleAutomationNotFound, AnsibleAutomationConflict)):
                raise
            raise AnsibleAutomationError(
                "Ansible execution stopped; inspect the immutable execution record and reconcile Devices before retrying"
            ) from exc
        finally:
            if leases is not None:
                leases.release()
