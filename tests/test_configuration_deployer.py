from __future__ import annotations

import json
from types import SimpleNamespace
import shlex

import pytest

from lib.repositories import SQLiteDatabase
from lib.services.configuration_profile_service import ConfigurationProfileService
from lib.services.configuration_schema_registry import ConfigurationSchemaRegistry
from lib.services.configuration_deployer import (
    ConfigurationDeploymentConflict, ConfigurationDeploymentService, ConfigurationDeploymentError,
)
from lib.services.credential_vault import CredentialVaultService
from lib.services.device_inventory import DeviceInventoryService
from lib.services.resource_lock import ResourceLockManager


class MemorySecretStore:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        return self.values.pop(key, None) is not None


class FakeCommandRunner:
    instances = []

    def __init__(self, spec):
        self.spec = spec
        self.commands = []
        self.values = {
            "wireless.radio0.country": "US",
            "wireless.radio0.channel": "36",
            "wireless.@wifi-iface[0].ssid": "NetRegress-Lab",
            "wireless.@wifi-iface[0].encryption": "psk2",
            "wireless.@wifi-iface[0].disabled": "0",
        }
        self.__class__.instances.append(self)

    def execute_script(self, script, *, timeout):
        self.commands.append(("script", script, timeout))
        for line in script.splitlines():
            try:
                tokens = shlex.split(line)
            except ValueError:
                continue
            if len(tokens) == 4 and tokens[:3] == ["uci", "-q", "get"]:
                return SimpleNamespace(
                    transport_succeeded=True, exit_code=0,
                    stdout=self.values.get(tokens[3], ""), stderr="",
                )
        return SimpleNamespace(transport_succeeded=True, exit_code=0, stdout="", stderr="")

    def close(self):
        return None


@pytest.fixture
def deploy_stack(tmp_path):
    FakeCommandRunner.instances.clear()
    database = SQLiteDatabase(tmp_path / "configuration-deploy.sqlite")
    database.initialize()
    now = "2026-11-15T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at)
               VALUES('org-1','org','Organization','ACTIVE',?,?)""", (now, now),
        )
        connection.execute(
            """INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at)
               VALUES('project-1','org-1','wireless','Wireless','ACTIVE',?,?)""", (now, now),
        )
        connection.execute(
            """INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at)
               VALUES('lab-1','project-1','Wireless Lab','gns3',1,'ACTIVE',?,?)""", (now, now),
        )
    inventory = DeviceInventoryService(database)
    device = inventory.create({
        "project_id": "project-1", "lab_id": "lab-1",
        "device_key": "openwrt-ap-1", "name": "OpenWrt AP",
        "device_type": "ROUTER", "host": "192.168.1.2", "port": 22,
        "vendor": "OpenWrt", "model": "OpenWrt AP",
    }, actor="owner")
    store = MemorySecretStore()
    vault = CredentialVaultService(database, store, secret_provider="test-os-vault")
    ssh = vault.create(
        project_id="project-1", device_id=device["device_id"], label="SSH admin",
        credential_type="SSH_PASSWORD", username="root", secret="ssh-secret-value", actor="owner",
    )
    psk = vault.create(
        project_id="project-1", device_id=device["device_id"], label="Lab Wi-Fi PSK",
        credential_type="WIFI_PSK", username=None, secret="wifi-password-123", actor="owner",
    )
    schemas = ConfigurationSchemaRegistry(database)
    schema = schemas.register(
        project_id="project-1", schema_id="openwrt.wifi.v1", version=1,
        name="OpenWrt Wi-Fi v1",
        definition={
            "type": "object",
            "properties": {
                "radio_section": {"type": "string", "minLength": 1, "maxLength": 32},
                "interface_section": {"type": "string", "minLength": 1, "maxLength": 32},
                "ssid": {"type": "string", "minLength": 1, "maxLength": 32},
                "country": {"type": "string", "minLength": 2, "maxLength": 2},
                "channel": {"type": "integer", "minimum": 1, "maximum": 196},
                "encryption": {"type": "string", "enum": ["psk2", "sae", "psk-mixed"]},
                "enabled": {"type": "boolean"},
            },
            "required": [
                "radio_section", "interface_section", "ssid", "country",
                "channel", "encryption", "enabled",
            ],
            "additionalProperties": False,
        },
        actor="owner",
    )
    profiles = ConfigurationProfileService(database, schemas)
    profile = profiles.create_profile(
        project_id="project-1", name="Wireless deployment", description="Managed Wi-Fi",
        scope_type="DEVICE", scope_id=device["device_id"],
        schema_record_id=schema["schema_record_id"], actor="owner", device_exists=True,
    )
    revision = profiles.create_revision(
        profile["profile_id"],
        values={
            "radio_section": "radio0", "interface_section": "@wifi-iface[0]",
            "ssid": "NetRegress-Lab", "country": "US", "channel": 36,
            "encryption": "psk2", "enabled": True,
        },
        actor="owner",
    )
    revision = profiles.publish(profile["profile_id"], revision["revision_id"], actor="owner")
    deployer = ConfigurationDeploymentService(
        database, profiles, vault,
        resource_lock_manager=ResourceLockManager(tmp_path / "locks"),
        runner_factory=FakeCommandRunner,
    )
    ids = {
        "device_id": device["device_id"], "profile_id": profile["profile_id"],
        "revision_id": revision["revision_id"], "ssh_credential_id": ssh["credential_id"],
        "wifi_psk_credential_id": psk["credential_id"],
    }
    return database, store, deployer, revision, ids


def test_deployment_plan_is_metadata_only_and_hash_bound(deploy_stack):
    _database, _store, deployer, revision, ids = deploy_stack
    plan = deployer.plan(
        ids["profile_id"], ids["revision_id"], device_id=ids["device_id"],
        ssh_credential_id=ids["ssh_credential_id"],
        wifi_psk_credential_id=ids["wifi_psk_credential_id"], actor="owner",
    )
    assert plan["configuration_hash"] == revision["configuration_hash"]
    assert plan["adapter"] == "openwrt-uci-wifi-v1"
    assert "wifi-password-123" not in json.dumps(plan)
    assert "ssh-secret-value" not in json.dumps(plan)
    assert FakeCommandRunner.instances == []


def test_deployment_uses_scoped_credentials_fixed_uci_allowlist_and_audited_evidence(deploy_stack):
    database, store, deployer, revision, ids = deploy_stack
    plan = deployer.plan(
        ids["profile_id"], ids["revision_id"], device_id=ids["device_id"],
        ssh_credential_id=ids["ssh_credential_id"],
        wifi_psk_credential_id=ids["wifi_psk_credential_id"], actor="owner",
    )
    result = deployer.deploy(
        ids["profile_id"], ids["revision_id"], device_id=ids["device_id"],
        ssh_credential_id=ids["ssh_credential_id"],
        wifi_psk_credential_id=ids["wifi_psk_credential_id"],
        expected_sha256=revision["configuration_hash"], confirmed=True, actor="owner",
    )
    assert result["status"] == "APPLIED"
    assert result["result"]["verified_fields"] == ["country", "channel", "ssid", "encryption", "disabled"]
    assert result["result"]["assignment_id"]
    runner = FakeCommandRunner.instances[-1]
    command = next(item[1] for item in runner.commands if item[0] == "script" and "uci set" in item[1])
    assert "wifi-password-123" in command
    assert "uci set" in command
    assert "NetRegress-Lab" in command
    assert "wireless.radio0.channel" in command
    assert "ssh-secret-value" not in json.dumps(result)
    assert "wifi-password-123" not in json.dumps(result)
    assert "wifi-password-123" not in repr(plan)
    with database.connection() as connection:
        row = connection.execute(
            "SELECT * FROM device_configuration_deployments WHERE deployment_id=?",
            (result["deployment_id"],),
        ).fetchone()
        assert row["status"] == "APPLIED"
        assert "wifi-password-123" not in repr(dict(row))
        assert "ssh-secret-value" not in repr(dict(row))
        actions = {
            row[0] for row in connection.execute(
                "SELECT action FROM audit_events WHERE resource_type='DEVICE_CONFIGURATION_DEPLOYMENT'"
            ).fetchall()
        }
        assert "DEVICE_CONFIGURATION_DEPLOYMENT_STARTED" in actions
        assert "DEVICE_CONFIGURATION_DEPLOYMENT_APPLIED" in actions
    assert len(store.values) == 2


def test_deployment_requires_confirmation_exact_hash_and_matching_device_credentials(deploy_stack):
    _database, _store, deployer, revision, ids = deploy_stack
    args = {
        "device_id": ids["device_id"], "ssh_credential_id": ids["ssh_credential_id"],
        "wifi_psk_credential_id": ids["wifi_psk_credential_id"],
        "expected_sha256": revision["configuration_hash"], "actor": "owner",
    }
    with pytest.raises(ConfigurationDeploymentConflict, match="explicit confirmation"):
        deployer.deploy(ids["profile_id"], ids["revision_id"], **args, confirmed=False)
    with pytest.raises(ConfigurationDeploymentConflict, match="hash changed"):
        deployer.deploy(ids["profile_id"], ids["revision_id"], **{**args, "expected_sha256": "0" * 64}, confirmed=True)
    with pytest.raises(ConfigurationDeploymentConflict, match="same-device WIFI_PSK"):
        deployer.plan(
            ids["profile_id"], ids["revision_id"], device_id=ids["device_id"],
            ssh_credential_id=ids["ssh_credential_id"], wifi_psk_credential_id="another-device-credential",
            actor="owner",
        )
    assert FakeCommandRunner.instances == []


def test_unsupported_adapter_fields_and_shell_injection_are_rejected(deploy_stack):
    _database, _store, deployer, _revision, _ids = deploy_stack
    base = {
        "radio_section": "radio0", "interface_section": "@wifi-iface[0]",
        "ssid": "SafeSSID", "country": "US", "channel": 36,
        "encryption": "psk2", "enabled": True,
    }
    with pytest.raises(ConfigurationDeploymentError, match="unknown"):
        deployer.normalize_values({**base, "command": "reboot"})
    with pytest.raises(ConfigurationDeploymentError, match="control characters"):
        deployer.normalize_values({**base, "ssid": "safe\nuci commit"})
    with pytest.raises(ConfigurationDeploymentError, match="radio_section"):
        deployer.normalize_values({**base, "radio_section": "radio0; reboot"})


def test_device_lock_prevents_concurrent_configuration_push(deploy_stack, tmp_path):
    _database, _store, deployer, revision, ids = deploy_stack
    lease = deployer.resource_lock_manager.acquire(
        "device:" + ids["device_id"], "test-lock", timeout=0.0, lease_seconds=300.0,
    )
    try:
        with pytest.raises(ConfigurationDeploymentConflict, match="locked"):
            deployer.deploy(
                ids["profile_id"], ids["revision_id"], device_id=ids["device_id"],
                ssh_credential_id=ids["ssh_credential_id"],
                wifi_psk_credential_id=ids["wifi_psk_credential_id"],
                expected_sha256=revision["configuration_hash"], confirmed=True, actor="owner",
            )
        assert FakeCommandRunner.instances == []
    finally:
        lease.release()


def test_unsupported_vendor_or_schema_fails_before_network_writes(deploy_stack):
    database, _store, deployer, revision, ids = deploy_stack
    with database.transaction(immediate=True) as connection:
        connection.execute("UPDATE devices SET vendor='Unknown' WHERE device_id=?", (ids["device_id"],))
    with pytest.raises(ConfigurationDeploymentConflict, match="OpenWrt ROUTER"):
        deployer.plan(
            ids["profile_id"], ids["revision_id"], device_id=ids["device_id"],
            ssh_credential_id=ids["ssh_credential_id"],
            wifi_psk_credential_id=ids["wifi_psk_credential_id"], actor="owner",
        )
    assert FakeCommandRunner.instances == []


def test_configuration_deployment_api_is_idempotent_and_requires_permissions(
    deploy_stack, monkeypatch,
):
    from dashboard import api_v1 as api_module
    from dashboard.app import create_app
    from lib.security import AuthManager

    database, store, _deployer, revision, ids = deploy_stack

    class FakeAdapter:
        descriptor = SimpleNamespace(family=SimpleNamespace(value="test-os-vault"))

        def create_secret_store(self):
            return store

    monkeypatch.setattr(api_module, "platform_adapter_for", lambda: FakeAdapter())
    from lib.services import configuration_deployer as deploy_module
    monkeypatch.setattr(deploy_module, "_ParamikoScriptRunner", FakeCommandRunner)

    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()
    payload = {
        "revision_id": ids["revision_id"],
        "device_id": ids["device_id"],
        "ssh_credential_id": ids["ssh_credential_id"],
        "wifi_psk_credential_id": ids["wifi_psk_credential_id"],
    }
    planned = client.post(
        "/api/v1/configuration/profiles/" + ids["profile_id"] + "/deploy-plan",
        json=payload,
    )
    assert planned.status_code == 200
    assert planned.get_json()["data"]["plan"]["configuration_hash"] == revision["configuration_hash"]
    assert FakeCommandRunner.instances == []

    request_payload = {
        **payload, "expected_sha256": revision["configuration_hash"], "confirmed": True,
    }
    headers = {"Idempotency-Key": "openwrt-config-deploy-api-1"}
    deployed = client.post(
        "/api/v1/configuration/profiles/" + ids["profile_id"] + "/deploy",
        json=request_payload, headers=headers,
    )
    assert deployed.status_code == 200
    deployment_id = deployed.get_json()["data"]["deployment_id"]
    command_count = len(FakeCommandRunner.instances[-1].commands)
    repeated = client.post(
        "/api/v1/configuration/profiles/" + ids["profile_id"] + "/deploy",
        json=request_payload, headers=headers,
    )
    assert repeated.status_code == 200
    assert repeated.get_json()["data"]["deployment_id"] == deployment_id
    assert len(FakeCommandRunner.instances[-1].commands) == command_count

    history = client.get(
        "/api/v1/configuration/devices/" + ids["device_id"] + "/deployments",
    )
    assert history.status_code == 200
    assert [item["deployment_id"] for item in history.get_json()["data"]["items"]] == [deployment_id]
