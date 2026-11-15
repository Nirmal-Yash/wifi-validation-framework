"""Schema-gated OpenWrt Wi-Fi deployment with explicit authorization and evidence.

This adapter intentionally supports one declared schema. It does not translate
arbitrary configuration values or YAML into shell commands.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import secrets
import shlex
from pathlib import Path
from typing import Any, Mapping

import paramiko

from lib.services.command_runner import SSHConnectionSpec
from lib.services.resource_lock import ResourceLockError, ResourceLockManager


class ConfigurationDeploymentError(RuntimeError):
    """A configuration deployment was rejected or failed safely."""


class ConfigurationDeploymentNotFound(LookupError):
    """The target Device, Profile or Revision is outside the requested scope."""


class ConfigurationDeploymentConflict(ConfigurationDeploymentError):
    """The revision or device is not in a deployable state."""


class _ScriptResult:
    def __init__(self, exit_code: int, stdout: str = "", stderr: str = ""):
        self.transport_succeeded = True
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class _ParamikoScriptRunner:
    """SSH script transport that sends configuration over channel stdin.

    The Wi-Fi PSK never appears in the remote command line; it travels only
    inside the authenticated SSH channel.
    """

    def __init__(self, spec: SSHConnectionSpec):
        self.spec = spec
        self.client = None

    def _connect(self):
        if self.client is not None and self.client.get_transport() is not None:
            return self.client
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            hostname=self.spec.host, port=self.spec.port, username=self.spec.username,
            password=self.spec.password, look_for_keys=False, allow_agent=False,
            timeout=10, auth_timeout=10, banner_timeout=10,
        )
        self.client = client
        return client

    def execute_script(self, script: str, *, timeout: float) -> _ScriptResult:
        client = self._connect()
        stdin, stdout, stderr = client.exec_command("sh -s", timeout=timeout, get_pty=False)
        stdin.write(script)
        stdin.flush()
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return _ScriptResult(stdout.channel.recv_exit_status(), out, err)

    def close(self):
        if self.client is not None:
            try:
                self.client.close()
            finally:
                self.client = None


class ConfigurationDeploymentService:
    SCHEMA_ID = "openwrt.wifi.v1"
    SCHEMA_VERSION = 1
    _RADIO_SECTION = re.compile(r"^radio[0-9]{1,2}$")
    _INTERFACE_SECTION = re.compile(r"^(?:@wifi-iface\[[0-9]{1,3}\]|[a-z][a-z0-9_]{0,31})$")
    _COUNTRY = re.compile(r"^[A-Z]{2}$")
    _ENCRYPTION = frozenset({"psk2", "sae", "psk-mixed"})
    _FIELDS = frozenset({
        "radio_section", "interface_section", "ssid", "country",
        "channel", "encryption", "enabled",
    })

    def __init__(
        self, database, configuration_profiles, credential_vault, *,
        resource_lock_manager=None, runner_factory=None,
    ):
        self.database = database
        self.configuration_profiles = configuration_profiles
        self.credential_vault = credential_vault
        self.runner_factory = runner_factory or _ParamikoScriptRunner
        if resource_lock_manager is None:
            directory = Path(
                os.getenv("NETREGRESS_LOCK_DIRECTORY")
                or (Path(database.path).resolve().parent / "locks")
            )
            resource_lock_manager = ResourceLockManager(directory)
        self.resource_lock_manager = resource_lock_manager

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise ConfigurationDeploymentError("actor must contain 1 to 128 printable characters")
        return actor

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _audit(connection, actor: str, action: str, deployment_id: str, details: dict) -> None:
        connection.execute(
            """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("AUD-" + secrets.token_hex(12), actor, action, "DEVICE_CONFIGURATION_DEPLOYMENT",
             deployment_id, ConfigurationDeploymentService._canonical(details),
             ConfigurationDeploymentService._now()),
        )

    @classmethod
    def normalize_values(cls, values: object) -> dict:
        if not isinstance(values, Mapping):
            raise ConfigurationDeploymentError("OpenWrt Wi-Fi configuration values must be an object")
        if set(values) != cls._FIELDS:
            missing = sorted(cls._FIELDS - set(values))
            unknown = sorted(set(values) - cls._FIELDS)
            raise ConfigurationDeploymentError(
                "OpenWrt Wi-Fi schema fields do not match the supported contract "
                f"(missing={missing}, unknown={unknown})"
            )
        radio = values.get("radio_section")
        interface = values.get("interface_section")
        ssid = values.get("ssid")
        country = values.get("country")
        channel = values.get("channel")
        encryption = values.get("encryption")
        enabled = values.get("enabled")
        if not isinstance(radio, str) or not cls._RADIO_SECTION.fullmatch(radio):
            raise ConfigurationDeploymentError("radio_section must be a registered OpenWrt radio section such as radio0")
        if not isinstance(interface, str) or not cls._INTERFACE_SECTION.fullmatch(interface):
            raise ConfigurationDeploymentError("interface_section must be an OpenWrt wifi-iface section identifier")
        if (
            not isinstance(ssid, str) or not ssid or len(ssid.encode("utf-8")) > 32
            or any(ord(char) < 32 or ord(char) == 127 for char in ssid)
        ):
            raise ConfigurationDeploymentError("SSID must contain 1 to 32 UTF-8 bytes without control characters")
        if not isinstance(country, str) or not cls._COUNTRY.fullmatch(country):
            raise ConfigurationDeploymentError("country must be a two-letter uppercase country code")
        if isinstance(channel, bool) or not (
            channel == "auto" or (isinstance(channel, int) and 1 <= channel <= 196)
        ):
            raise ConfigurationDeploymentError("channel must be 'auto' or an integer from 1 to 196")
        if encryption not in cls._ENCRYPTION:
            raise ConfigurationDeploymentError("encryption must be psk2, sae or psk-mixed")
        if not isinstance(enabled, bool):
            raise ConfigurationDeploymentError("enabled must be a boolean")
        return {
            "radio_section": radio, "interface_section": interface, "ssid": ssid,
            "country": country, "channel": channel, "encryption": encryption,
            "enabled": enabled,
        }

    @staticmethod
    def _validate_psk(value: object) -> str:
        if not isinstance(value, str):
            raise ConfigurationDeploymentError("a separate WIFI_PSK vault credential is required")
        valid_ascii = 8 <= len(value) <= 63 and all(32 <= ord(char) <= 126 for char in value)
        valid_hex = len(value) == 64 and re.fullmatch(r"[A-Fa-f0-9]{64}", value) is not None
        if not (valid_ascii or valid_hex):
            raise ConfigurationDeploymentError("WIFI_PSK must be 8–63 printable ASCII characters or 64 hexadecimal characters")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ConfigurationDeploymentError("WIFI_PSK cannot contain control characters")
        return value

    def _load_scope(
        self, profile_id: str, revision_id: str, device_id: str,
        ssh_credential_id: str, wifi_psk_credential_id: str,
    ) -> tuple[dict, dict, dict, dict, dict]:
        profile = self.configuration_profiles.get_profile(profile_id)
        revision = self.configuration_profiles.get_revision(revision_id)
        if profile is None or revision is None or revision.get("profile_id") != profile_id:
            raise ConfigurationDeploymentNotFound("configuration profile or revision not found")
        if profile.get("scope_type") != "DEVICE" or profile.get("scope_id") != device_id:
            raise ConfigurationDeploymentConflict("deployment requires a Device-scoped profile assigned to this exact Device")
        if profile.get("status") != "PUBLISHED" or revision.get("status") != "PUBLISHED":
            raise ConfigurationDeploymentConflict("deployment requires an active profile and published immutable revision")
        if revision.get("schema_record_id") != profile.get("schema_record_id"):
            raise ConfigurationDeploymentConflict("revision schema does not match the selected profile")
        with self.database.connection() as connection:
            schema = connection.execute(
                "SELECT schema_record_id,project_id,schema_id,version,status FROM configuration_schemas WHERE schema_record_id=?",
                (profile["schema_record_id"],),
            ).fetchone()
            device = connection.execute(
                """SELECT d.device_id,d.project_id,d.lab_id,d.name,d.device_type,d.host,d.port,
                          d.vendor,d.status,l.status AS lab_status,p.status AS project_status
                   FROM devices d
                   JOIN labs l ON l.lab_id=d.lab_id AND l.project_id=d.project_id
                   JOIN projects p ON p.project_id=d.project_id
                   WHERE d.device_id=?""",
                (device_id,),
            ).fetchone()
        if schema is None or schema["project_id"] != profile["project_id"]:
            raise ConfigurationDeploymentNotFound("registered configuration schema not found in this Project")
        if schema["schema_id"] != self.SCHEMA_ID or int(schema["version"]) != self.SCHEMA_VERSION or schema["status"] != "ACTIVE":
            raise ConfigurationDeploymentConflict(
                f"only active {self.SCHEMA_ID} v{self.SCHEMA_VERSION} schemas have a deployment adapter"
            )
        if device is None:
            raise ConfigurationDeploymentNotFound("target Device was not found")
        if (
            device["project_id"] != profile["project_id"] or device["status"] != "ACTIVE"
            or device["lab_status"] != "ACTIVE" or device["project_status"] != "ACTIVE"
        ):
            raise ConfigurationDeploymentConflict("target Device, Lab and Project must be active in the same Project")
        if device["device_type"] != "ROUTER" or str(device["vendor"] or "").strip().lower() != "openwrt":
            raise ConfigurationDeploymentConflict("the openwrt.wifi.v1 adapter only supports registered OpenWrt ROUTER devices")
        values = self.normalize_values(revision.get("values"))
        ssh = self.credential_vault.get(ssh_credential_id)
        wifi = self.credential_vault.get(wifi_psk_credential_id)
        if (
            ssh is None or ssh.get("project_id") != device["project_id"]
            or ssh.get("device_id") != device_id or ssh.get("credential_type") != "SSH_PASSWORD"
            or ssh.get("status") != "ACTIVE" or not ssh.get("username")
        ):
            raise ConfigurationDeploymentConflict("an active same-device SSH_PASSWORD credential is required")
        if (
            wifi is None or wifi.get("project_id") != device["project_id"]
            or wifi.get("device_id") != device_id or wifi.get("credential_type") != "WIFI_PSK"
            or wifi.get("status") != "ACTIVE"
        ):
            raise ConfigurationDeploymentConflict("an active same-device WIFI_PSK credential is required")
        return profile, revision, dict(device), ssh, wifi

    def plan(
        self, profile_id: str, revision_id: str, *, device_id: str,
        ssh_credential_id: str, wifi_psk_credential_id: str, actor: str,
    ) -> dict:
        actor = self._actor(actor)
        profile, revision, device, ssh, wifi = self._load_scope(
            profile_id, revision_id, device_id, ssh_credential_id, wifi_psk_credential_id,
        )
        values = self.normalize_values(revision["values"])
        # A dry-run intentionally reads metadata only. It does not resolve secrets
        # or open a network connection.
        return {
            "profile_id": profile_id, "revision_id": revision_id,
            "schema_id": self.SCHEMA_ID, "schema_version": self.SCHEMA_VERSION,
            "configuration_hash": revision["configuration_hash"],
            "project_id": profile["project_id"], "lab_id": device["lab_id"],
            "device_id": device_id, "device_name": device["name"],
            "adapter": "openwrt-uci-wifi-v1",
            "field_names": sorted(values),
            "target": {"radio_section": values["radio_section"], "interface_section": values["interface_section"]},
            "non_secret_values": {
                key: values[key] for key in ("ssid", "country", "channel", "encryption", "enabled")
            },
            "ssh_credential_id": ssh["credential_id"],
            "wifi_psk_credential_id": wifi["credential_id"],
            "operations": [
                "validate immutable revision and same-device credentials",
                "set fixed OpenWrt UCI wireless fields",
                "commit wireless configuration and reload Wi-Fi",
                "verify non-secret fields by read-back",
                "assign the published revision to the Device after verification",
            ],
            "requires_explicit_confirmation": True,
        }

    @staticmethod
    def _command_result_ok(result: object) -> bool:
        return bool(
            getattr(result, "transport_succeeded", False)
            and getattr(result, "exit_code", None) == 0
        )

    def _execute_openwrt(self, runner, values: dict, psk: str) -> dict:
        psk = self._validate_psk(psk)
        radio = values["radio_section"]
        interface = values["interface_section"]
        assignments = [
            (f"wireless.{radio}.country", values["country"]),
            (f"wireless.{radio}.channel", str(values["channel"])),
            (f"wireless.{interface}.ssid", values["ssid"]),
            (f"wireless.{interface}.encryption", values["encryption"]),
            (f"wireless.{interface}.key", psk),
            (f"wireless.{interface}.disabled", "0" if values["enabled"] else "1"),
        ]
        commands = ["uci set " + shlex.quote(key + "=" + str(value)) for key, value in assignments]
        commands.extend(["uci commit wireless", "wifi reload"])
        # OpenWrt receives the fixed script through SSH stdin. Only the
        # harmless shell interpreter token appears in the remote process list.
        script = "set -eu\n" + "\n".join(commands) + "\n"
        result = runner.execute_script(script, timeout=90.0)
        if not self._command_result_ok(result):
            raise ConfigurationDeploymentError("OpenWrt rejected the configuration apply script or SSH transport failed")

        expected = {
            "country": (f"wireless.{radio}.country", values["country"]),
            "channel": (f"wireless.{radio}.channel", str(values["channel"])),
            "ssid": (f"wireless.{interface}.ssid", values["ssid"]),
            "encryption": (f"wireless.{interface}.encryption", values["encryption"]),
            "disabled": (f"wireless.{interface}.disabled", "0" if values["enabled"] else "1"),
        }
        verified = []
        for name, (uci_path, value) in expected.items():
            verification = runner.execute_script(
                "set -eu\nuci -q get " + shlex.quote(uci_path) + "\n",
                timeout=20.0,
            )
            actual = str(getattr(verification, "stdout", "")).strip()
            if not self._command_result_ok(verification) or actual != value:
                raise ConfigurationDeploymentError(
                    f"OpenWrt read-back verification failed for the {name} field"
                )
            verified.append(name)
        return {
            "adapter": "openwrt-uci-wifi-v1",
            "verified_fields": verified,
            "configuration_hash": None,
            "secret_material_persisted": False,
        }

    def _insert_record(self, plan: dict, profile: dict, revision: dict, device: dict, actor: str) -> str:
        deployment_id = "cfgd_" + secrets.token_hex(12)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO device_configuration_deployments(
                   deployment_id,project_id,lab_id,device_id,profile_id,revision_id,
                   schema_record_id,configuration_hash,status,plan_json,result_json,
                   created_at,started_at,completed_at,created_by
                   ) VALUES(?,?,?,?,?,?,?,?,'APPLYING',?,'{}',?,?,NULL,?)""",
                (deployment_id, profile["project_id"], device["lab_id"], device["device_id"],
                 profile["profile_id"], revision["revision_id"], revision["schema_record_id"],
                 revision["configuration_hash"], self._canonical(plan), now, now, actor),
            )
            self._audit(connection, actor, "DEVICE_CONFIGURATION_DEPLOYMENT_STARTED",
                        deployment_id, {"project_id": profile["project_id"],
                                        "lab_id": device["lab_id"], "device_id": device["device_id"],
                                        "profile_id": profile["profile_id"],
                                        "revision_id": revision["revision_id"]})
        return deployment_id

    def _finish_record(self, deployment_id: str, *, status: str, result: dict, actor: str) -> None:
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE device_configuration_deployments
                   SET status=?,result_json=?,completed_at=?
                   WHERE deployment_id=? AND status='APPLYING'""",
                (status, self._canonical(result), now, deployment_id),
            )
            if cursor.rowcount != 1:
                raise ConfigurationDeploymentError("deployment evidence changed before completion")
            self._audit(connection, actor, "DEVICE_CONFIGURATION_DEPLOYMENT_" + status,
                        deployment_id, {"status": status, "result": result})

    def deploy(
        self, profile_id: str, revision_id: str, *, device_id: str,
        ssh_credential_id: str, wifi_psk_credential_id: str,
        expected_sha256: str, confirmed: bool, actor: str,
    ) -> dict:
        actor = self._actor(actor)
        if confirmed is not True:
            raise ConfigurationDeploymentConflict("explicit confirmation is required before changing a Device")
        profile, revision, device, ssh, wifi = self._load_scope(
            profile_id, revision_id, device_id, ssh_credential_id, wifi_psk_credential_id,
        )
        if expected_sha256 != revision["configuration_hash"]:
            raise ConfigurationDeploymentConflict("configuration revision hash changed; request a fresh dry-run")
        plan = self.plan(
            profile_id, revision_id, device_id=device_id,
            ssh_credential_id=ssh_credential_id, wifi_psk_credential_id=wifi_psk_credential_id,
            actor=actor,
        )
        try:
            lease = self.resource_lock_manager.acquire(
                "device:" + device_id, "configuration-deploy:" + actor[:80],
                timeout=0.0, lease_seconds=600.0,
            )
        except (ResourceLockError, OSError, ValueError) as exc:
            raise ConfigurationDeploymentConflict("Device is locked by another operation; no configuration was sent") from exc
        deployment_id = None
        execution_started = False
        try:
            # Re-read all immutable scope and hash preconditions under the lock.
            profile, revision, device, ssh, wifi = self._load_scope(
                profile_id, revision_id, device_id, ssh_credential_id, wifi_psk_credential_id,
            )
            if expected_sha256 != revision["configuration_hash"]:
                raise ConfigurationDeploymentConflict("configuration revision hash changed; no configuration was sent")
            deployment_id = self._insert_record(plan, profile, revision, device, actor)
            values = self.normalize_values(revision["values"])

            def with_wifi_psk(wifi_record: Mapping[str, object], wifi_secret: str):
                validated_psk = self._validate_psk(wifi_secret)
                def with_ssh(ssh_record: Mapping[str, object], ssh_secret: str):
                    runner = self.runner_factory(SSHConnectionSpec(
                        target=device_id, host=device["host"], port=int(device["port"]),
                        username=str(ssh_record.get("username") or ""),
                        password=ssh_secret,
                    ))
                    try:
                        nonlocal execution_started
                        execution_started = True
                        return self._execute_openwrt(runner, values, validated_psk)
                    finally:
                        runner.close()
                return self.credential_vault.use_secret(
                    ssh_credential_id, project_id=profile["project_id"], device_id=device_id,
                    credential_type="SSH_PASSWORD", actor=actor, consumer=with_ssh,
                )

            result = self.credential_vault.use_secret(
                wifi_psk_credential_id, project_id=profile["project_id"], device_id=device_id,
                credential_type="WIFI_PSK", actor=actor, consumer=with_wifi_psk,
            )
            result["configuration_hash"] = revision["configuration_hash"]
            assignment = self.configuration_profiles.apply(
                profile_id, revision_id, target_type="DEVICE", target_id=device_id, actor=actor,
            )
            result["assignment_id"] = assignment["assignment_id"]
            result["secret_material_persisted"] = False
            self._finish_record(deployment_id, status="APPLIED", result=result, actor=actor)
            return self.get_deployment(deployment_id) or {
                "deployment_id": deployment_id, "status": "APPLIED", "result": result,
            }
        except (ConfigurationDeploymentError, ConfigurationDeploymentNotFound, ConfigurationDeploymentConflict) as exc:
            if deployment_id is not None:
                self._finish_record(
                    deployment_id, status="PARTIAL" if execution_started else "FAILED",
                    result={"error": "deployment was not verified", "error_type": type(exc).__name__,
                            "provider_changes_may_have_occurred": execution_started},
                    actor=actor,
                )
            raise
        except Exception as exc:
            if deployment_id is not None:
                self._finish_record(
                    deployment_id, status="PARTIAL" if execution_started else "FAILED",
                    result={"error": "deployment failed; inspect the evidence and verify device state before retrying",
                            "error_type": type(exc).__name__,
                            "provider_changes_may_have_occurred": execution_started},
                    actor=actor,
                )
            raise ConfigurationDeploymentError(
                "device configuration deployment failed safely; inspect deployment evidence before retrying"
            ) from exc
        finally:
            lease.release()

    def get_deployment(self, deployment_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM device_configuration_deployments WHERE deployment_id=?",
                (deployment_id,),
            ).fetchone()
        if row is None:
            return None
        result = {key: row[key] for key in (
            "deployment_id", "project_id", "lab_id", "device_id", "profile_id",
            "revision_id", "schema_record_id", "configuration_hash", "status",
            "created_at", "started_at", "completed_at", "created_by",
        )}
        result["plan"] = json.loads(row["plan_json"])
        result["result"] = json.loads(row["result_json"])
        return result

    def list_deployments(self, device_id: str, *, limit: int = 25) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, 100))
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT deployment_id FROM device_configuration_deployments WHERE device_id=? ORDER BY created_at DESC LIMIT ?",
                (device_id, limit),
            ).fetchall()
        return [self.get_deployment(row["deployment_id"]) for row in rows]
