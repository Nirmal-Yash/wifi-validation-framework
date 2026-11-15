from __future__ import annotations

import pytest

from lib.repositories import SQLiteDatabase
from lib.services.device_inventory import (
    DeviceInventoryError, DeviceInventoryNotFound, DeviceInventoryService,
)


@pytest.fixture
def inventory(tmp_path):
    database = SQLiteDatabase(tmp_path / "devices.sqlite")
    database.initialize()
    now = "2026-11-15T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-1", "org", "Organization", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-1", "org-1", "wireless", "Wireless", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-2", "org-1", "other", "Other", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-1", "project-1", "WiFi Lab", "gns3", 1, "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-2", "project-2", "Other Lab", "gns3", 1, "ACTIVE", now, now),
        )
    return database, DeviceInventoryService(database)


def payload(**updates):
    value = {
        "project_id": "project-1", "lab_id": "lab-1",
        "device_key": "router-east", "name": "East Router",
        "device_type": "ROUTER", "host": "192.168.10.1", "port": 22,
        "vendor": "Example", "model": "XR-1", "username": "admin",
        "capabilities": {"supports_ssh": True, "supports_firmware_flash": False},
        "metadata": {"site": "rack-1"},
    }
    value.update(updates)
    return value


def test_create_list_update_and_archive_device(inventory):
    _database, service = inventory
    created = service.create(payload(), actor="owner")
    assert created["device_id"].startswith("dev_")
    assert created["credential_id"] is None
    assert created["capabilities"]["supports_ssh"] is True
    assert service.list("project-1", lab_id="lab-1") == [created]

    updated = service.update(created["device_id"], {"name": "Core Router", "port": 2222}, actor="owner")
    assert updated["name"] == "Core Router"
    assert updated["port"] == 2222

    archived = service.update(created["device_id"], {"status": "ARCHIVED"}, actor="owner")
    assert archived["status"] == "ARCHIVED"
    assert service.list("project-1", status="ACTIVE") == []
    with pytest.raises(DeviceInventoryError, match="archived"):
        service.update(created["device_id"], {"name": "No longer active"}, actor="owner")


def test_duplicate_key_and_cross_project_lab_are_rejected(inventory):
    _database, service = inventory
    service.create(payload(), actor="owner")
    with pytest.raises(DeviceInventoryError, match="already exists"):
        service.create(payload(name="Duplicate"), actor="owner")
    with pytest.raises(DeviceInventoryNotFound, match="Lab not found"):
        service.create(payload(lab_id="lab-2"), actor="owner")


@pytest.mark.parametrize("host", ["", "bad host", "https://example.com", "../etc/passwd", "a..b"])
def test_host_validation_rejects_non_host_values(inventory, host):
    _database, service = inventory
    with pytest.raises(DeviceInventoryError, match="host"):
        service.create(payload(host=host), actor="owner")


def test_capabilities_and_metadata_reject_unknown_or_secret_fields(inventory):
    _database, service = inventory
    with pytest.raises(DeviceInventoryError, match="unknown device capability"):
        service.create(payload(capabilities={"supports_telnet": True}), actor="owner")
    with pytest.raises(DeviceInventoryError, match="credential-like"):
        service.create(payload(metadata={"password": "never-store"}), actor="owner")
    with pytest.raises(DeviceInventoryError, match="boolean"):
        service.create(payload(capabilities={"supports_ssh": "yes"}), actor="owner")


def test_device_credential_reference_must_match_project_and_exact_device(inventory):
    database, service = inventory
    created = service.create(payload(), actor="owner")
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO managed_credentials(
               credential_id,project_id,device_id,label,credential_type,username,secret_provider,
               secret_reference,status,verification_status,last_verified_at,verification_summary,
               rotated_at,created_at,updated_at,created_by,updated_by)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("cred-other", "project-1", "another-device", "SSH", "SSH_PASSWORD", "admin",
             "test", "opaque-reference", "ACTIVE", "NOT_VERIFIED", None, "", None,
             "2026-11-15T00:00:00+00:00", "2026-11-15T00:00:00+00:00", "owner", "owner"),
        )
    with pytest.raises(DeviceInventoryError, match="exact device"):
        service.update(created["device_id"], {"credential_id": "cred-other"}, actor="owner")

def test_device_inventory_api_is_project_scoped_idempotent_and_archives(tmp_path):
    from dashboard.app import create_app
    from lib.security import AuthManager

    database = SQLiteDatabase(tmp_path / "device-api.sqlite")
    database.initialize()
    now = "2026-11-15T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-api", "api-org", "API Org", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-api", "org-api", "api-project", "API Project", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-api", "project-api", "API Lab", "gns3", 1, "ACTIVE", now, now),
        )
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()
    payload = {
        "project_id": "project-api", "lab_id": "lab-api",
        "device_key": "api-router", "name": "API Router",
        "device_type": "ROUTER", "host": "192.168.50.1", "port": 22,
    }
    created = client.post(
        "/api/v1/devices", json=payload,
        headers={"Idempotency-Key": "stage-d-device-api-create-1"},
    )
    assert created.status_code == 201
    device_id = created.get_json()["data"]["device_id"]
    listed = client.get("/api/v1/devices?project_id=project-api")
    assert listed.status_code == 200
    assert [item["device_id"] for item in listed.get_json()["data"]["items"]] == [device_id]
    archived = client.patch(
        "/api/v1/devices/" + device_id, json={"status": "ARCHIVED"},
        headers={"Idempotency-Key": "stage-d-device-api-archive-1"},
    )
    assert archived.status_code == 200
    assert archived.get_json()["data"]["status"] == "ARCHIVED"
    assert client.get("/api/v1/devices?project_id=project-api").get_json()["data"]["items"] == []
