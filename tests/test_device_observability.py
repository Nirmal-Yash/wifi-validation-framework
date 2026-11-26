from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from lib.repositories import SQLiteDatabase
from lib.services.device_inventory import DeviceInventoryService
from lib.services.device_observation import (
    DeviceObservationError, DeviceObservationNotFound, DeviceObservationService,
)

OBSERVED = [
    {
        "ifindex": 2, "ifname": "eth0", "mtu": 1500, "flags": ["BROADCAST", "UP"],
        "stats64": {
            "rx": {"bytes": 1200, "packets": 12, "errors": 1, "dropped": 2},
            "tx": {"bytes": 2400, "packets": 24, "errors": 3, "dropped": 4},
        },
    }
]


class FakeRunner:
    def __init__(self, stdout=None, *, exit_code=0, transport_succeeded=True):
        self.stdout = json.dumps(OBSERVED) if stdout is None else stdout
        self.exit_code = exit_code
        self.transport_succeeded = transport_succeeded
        self.calls = []

    def execute(self, target, command, **kwargs):
        self.calls.append((target, command, kwargs))
        return SimpleNamespace(
            transport_succeeded=self.transport_succeeded,
            exit_code=self.exit_code,
            stdout=self.stdout,
            transport_error=None if self.transport_succeeded else "timeout",
        )


@pytest.fixture
def observation_env(tmp_path):
    database = SQLiteDatabase(tmp_path / "observations.sqlite")
    database.initialize()
    now = "2026-11-24T10:00:00+00:00"
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
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-2", "org-1", "project2", "Other Project", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-1", "project-1", "Lab", "gns3", 1, "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-2", "project-2", "Other Lab", "gns3", 1, "ACTIVE", now, now),
        )
    inventory = DeviceInventoryService(database)
    device = inventory.create({
        "project_id": "project-1", "lab_id": "lab-1",
        "device_key": "edge-router", "name": "Edge Router",
        "device_type": "ROUTER", "host": "192.0.2.10", "port": 22,
        "username": "observer",
    }, actor="owner")
    service = DeviceObservationService(
        database, clock=lambda: __import__("datetime").datetime(
            2026, 11, 24, 12, 0, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    return database, service, device


def test_capture_persists_observed_interface_counters_and_provenance(observation_env):
    database, service, device = observation_env
    runner = FakeRunner()
    captured = service.capture(device, runner, actor="operator")

    assert captured["device_id"] == device["device_id"]
    assert captured["source"] == "linux.ip-link-json"
    assert captured["snapshot"]["command"] == "ip -s -j link show"
    assert captured["snapshot"]["interfaces"][0]["counters"] == {
        "rx_bytes": 1200, "rx_packets": 12, "rx_errors": 1, "rx_dropped": 2,
        "tx_bytes": 2400, "tx_packets": 24, "tx_errors": 3, "tx_dropped": 4,
    }
    metrics = {item["metric"]: item for item in captured["snapshot"]["metrics"]}
    assert metrics["rx_bytes"]["value"] == 1200
    assert metrics["rx_bytes"]["unit"] == "bytes"
    assert metrics["rx_bytes"]["interface"] == "eth0"
    assert metrics["tx_errors"]["unit"] == "errors"
    assert runner.calls[0][1] == "ip -s -j link show"
    assert runner.calls[0][2]["command_category"] == "device_observability"
    assert runner.calls[0][2]["idempotent"] is True
    assert runner.calls[0][2]["privilege_mode"] == "USER"

    history = service.list_for_device(device["device_id"])
    assert len(history) == 1
    assert history[0]["observation_id"] == captured["observation_id"]
    assert history[0]["payload_sha256"] == captured["payload_sha256"]
    assert history[0]["snapshot"]["metrics"] == captured["snapshot"]["metrics"]
    with database.connection() as connection:
        row = connection.execute(
            "SELECT action,resource_id FROM audit_events WHERE resource_id=?",
            (captured["observation_id"],),
        ).fetchone()
    assert row["action"] == "DEVICE_OBSERVATION_RECORDED"


@pytest.mark.parametrize("runner", [
    FakeRunner(stdout="not-json"),
    FakeRunner(stdout="[]"),
    FakeRunner(stdout=json.dumps([{"ifname": "eth0", "stats64": {"rx": {}}}])),
    FakeRunner(exit_code=1),
    FakeRunner(transport_succeeded=False),
])
def test_failed_or_unmeasurable_capture_never_persists_a_snapshot(observation_env, runner):
    _database, service, device = observation_env
    with pytest.raises(DeviceObservationError):
        service.capture(device, runner, actor="operator")
    assert service.list_for_device(device["device_id"]) == []


def test_parser_omits_unavailable_counters_instead_of_inventing_zeroes():
    parsed = DeviceObservationService.parse_ip_link_stats(json.dumps([
        {"ifindex": 3, "ifname": "wlan0", "stats": {"rx": {"bytes": 0}, "tx": {}}}
    ]))
    assert parsed["interfaces"][0]["counters"] == {"rx_bytes": 0}
    assert parsed["warnings"] == []


def test_parser_rejects_untrusted_interface_names_and_invalid_counters():
    with pytest.raises(DeviceObservationError, match="invalid interface name"):
        DeviceObservationService.parse_ip_link_stats(json.dumps([
            {"ifname": "eth0;reboot", "stats64": {"rx": {"bytes": 1}}}
        ]))
    with pytest.raises(DeviceObservationError, match="no trustworthy"):
        DeviceObservationService.parse_ip_link_stats(json.dumps([
            {"ifname": "eth0", "stats64": {"rx": {"bytes": -1}}}
        ]))


def test_snapshot_scope_is_checked_against_database_device_and_lab(observation_env):
    _database, service, device = observation_env
    foreign = dict(device, project_id="project-2", lab_id="lab-2")
    with pytest.raises(DeviceObservationNotFound):
        service.capture(foreign, FakeRunner(), actor="operator")


def test_observation_rows_are_immutable_and_cannot_be_deleted(observation_env):
    database, service, device = observation_env
    captured = service.capture(device, FakeRunner(), actor="operator")
    with database.transaction(immediate=True) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE device_observation_snapshots SET observed_by='tampered' WHERE observation_id=?",
                (captured["observation_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            connection.execute(
                "DELETE FROM device_observation_snapshots WHERE observation_id=?",
                (captured["observation_id"],),
            )


def test_api_exposes_scoped_read_and_requires_linked_managed_credential_for_capture(tmp_path):
    from dashboard.app import create_app
    from lib.security import AuthManager

    database = SQLiteDatabase(tmp_path / "observations-api.sqlite")
    database.initialize()
    now = "2026-11-24T10:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-api", "org-api", "Org API", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-api", "org-api", "project-api", "Project API", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-api", "project-api", "Lab API", "gns3", 1, "ACTIVE", now, now),
        )
    device = DeviceInventoryService(database).create({
        "project_id": "project-api", "lab_id": "lab-api",
        "device_key": "api-router", "name": "API Router",
        "device_type": "ROUTER", "host": "192.0.2.20",
    }, actor="owner")
    client = create_app(database.path, auth_manager=AuthManager((), required=False)).test_client()
    response = client.get("/api/v1/devices/" + device["device_id"] + "/observations")
    assert response.status_code == 200
    assert response.get_json()["data"]["items"] == []
    capture = client.post(
        "/api/v1/devices/" + device["device_id"] + "/observations",
        headers={"Idempotency-Key": "device-observe-no-credential-1"},
    )
    assert capture.status_code == 409
    assert capture.get_json()["error"]["code"] == "DEVICE_CREDENTIAL_REQUIRED"


def test_fixed_observation_command_is_allowed_but_mutating_ip_commands_are_denied():
    from lib.services.command_security import CommandSecurityError, CommandSecurityPolicy

    policy = CommandSecurityPolicy.default()
    policy.validate("managed-device", "ip -s -j link show", shell=False)
    with pytest.raises(CommandSecurityError):
        policy.validate("managed-device", "ip link set eth0 down", shell=False)


def test_parser_bounds_untrusted_counter_values_and_raw_payload_size():
    oversized_counter = json.dumps([
        {"ifname": "eth0", "stats64": {"rx": {"bytes": 2**64}}}
    ])
    with pytest.raises(DeviceObservationError, match="no trustworthy"):
        DeviceObservationService.parse_ip_link_stats(oversized_counter)
    with pytest.raises(DeviceObservationError, match="two MiB"):
        DeviceObservationService.parse_ip_link_stats(" " * (2 * 1024 * 1024 + 1))


def test_api_rejects_devices_without_declared_ssh_capability(tmp_path):
    from dashboard.app import create_app
    from lib.security import AuthManager

    database = SQLiteDatabase(tmp_path / "observations-ssh-capability.sqlite")
    database.initialize()
    now = "2026-11-24T10:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-ssh", "org-ssh", "Org SSH", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-ssh", "org-ssh", "project-ssh", "Project SSH", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-ssh", "project-ssh", "Lab SSH", "gns3", 1, "ACTIVE", now, now),
        )
    device = DeviceInventoryService(database).create({
        "project_id": "project-ssh", "lab_id": "lab-ssh",
        "device_key": "no-ssh-router", "name": "No SSH Router",
        "device_type": "ROUTER", "host": "192.0.2.21",
        "capabilities": {"supports_ssh": False},
    }, actor="owner")
    client = create_app(database.path, auth_manager=AuthManager((), required=False)).test_client()
    response = client.post(
        "/api/v1/devices/" + device["device_id"] + "/observations",
        headers={"Idempotency-Key": "device-observe-no-ssh-capability-1"},
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "DEVICE_SSH_UNSUPPORTED"
