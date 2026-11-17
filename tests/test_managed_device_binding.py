from __future__ import annotations

from lib.repositories import SQLiteDatabase
from lib.services.device_inventory import DeviceInventoryService
from lib.services.managed_device_binding import (
    ManagedDeviceBindingError,
    build_managed_device_profile,
)


def _database(tmp_path):
    database = SQLiteDatabase(tmp_path / "managed-device.sqlite")
    database.initialize()
    now = "2026-11-17T06:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-1", "org", "Organization", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-1", "org-1", "project", "Project", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-1", "project-1", "Lab", "gns3", 1, "ACTIVE", now, now),
        )
    device = DeviceInventoryService(database).create({
        "project_id": "project-1", "lab_id": "lab-1", "device_key": "client_vm",
        "name": "Managed client", "device_type": "CLIENT", "host": "192.0.2.50",
        "port": 2222, "username": "inventory-user",
    }, actor="owner")
    return database, device


class FakeCredentialVault:
    def __init__(self, device, *, credential_type="SSH_PASSWORD", project_id="project-1"):
        self.device = device
        self.credential_type = credential_type
        self.project_id = project_id
        self.use_calls = []

    def get(self, credential_id):
        if credential_id != "credential-1":
            return None
        return {
            "credential_id": credential_id,
            "project_id": self.project_id,
            "device_id": self.device["device_id"],
            "credential_type": self.credential_type,
            "status": "ACTIVE",
            "username": "vault-user",
        }

    def use_secret(self, credential_id, *, project_id, device_id, credential_type, actor, consumer):
        self.use_calls.append((credential_id, project_id, device_id, credential_type, actor))
        consumer(self.get(credential_id), "secret-value-that-must-not-leak")
        return {"status": "resolved"}


def test_managed_device_profile_uses_vault_secret_and_inventory_endpoint(tmp_path):
    database, device = _database(tmp_path)
    vault = FakeCredentialVault(device)
    profiles = {
        "client_vm": {
            "host": "198.51.100.10",
            "username": "static-user",
            "password": "__ENV__:UNUSED_STATIC_PASSWORD",
            "key_filename": "/tmp/legacy-key",
            "device_type": "linux",
        },
    }

    profile, identity = build_managed_device_profile(
        database,
        vault,
        managed_device_id=device["device_id"],
        project_id="project-1",
        lab_id="lab-1",
        actor="pipeline-operator",
        ssh_credential_id="credential-1",
        device_profiles=profiles,
    )

    assert profile.host == "192.0.2.50"
    assert profile.port == 2222
    assert profile.username == "vault-user"
    assert profile.password == "secret-value-that-must-not-leak"
    assert profile.key_filename is None
    assert "secret-value-that-must-not-leak" not in repr(profile)
    assert identity == {
        "device_id": device["device_id"],
        "device_key": "client_vm",
        "host": "192.0.2.50",
        "port": 2222,
        "username": "vault-user",
        "ssh_credential_id": "credential-1",
    }
    assert vault.use_calls == [
        ("credential-1", "project-1", device["device_id"], "SSH_PASSWORD", "pipeline-operator"),
    ]


def test_managed_device_binding_rejects_cross_lab_before_secret_use(tmp_path):
    database, device = _database(tmp_path)
    vault = FakeCredentialVault(device)

    try:
        build_managed_device_profile(
            database, vault,
            managed_device_id=device["device_id"],
            project_id="project-1",
            lab_id="other-lab",
            actor="pipeline-operator",
            ssh_credential_id="credential-1",
            device_profiles={"client_vm": {"host": "127.0.0.1", "username": "u"}},
        )
    except ManagedDeviceBindingError as exc:
        assert "same Project/Lab" in str(exc)
    else:
        raise AssertionError("cross-Lab Device binding must be rejected")
    assert vault.use_calls == []


def test_managed_device_binding_rejects_wrong_credential_type(tmp_path):
    database, device = _database(tmp_path)
    vault = FakeCredentialVault(device, credential_type="WIFI_PSK")

    try:
        build_managed_device_profile(
            database, vault,
            managed_device_id=device["device_id"],
            project_id="project-1",
            lab_id="lab-1",
            actor="pipeline-operator",
            ssh_credential_id="credential-1",
            device_profiles={"client_vm": {"host": "127.0.0.1", "username": "u"}},
        )
    except ManagedDeviceBindingError as exc:
        assert "SSH_PASSWORD" in str(exc)
    else:
        raise AssertionError("a WIFI_PSK credential must not be used for SSH")
    assert vault.use_calls == []
