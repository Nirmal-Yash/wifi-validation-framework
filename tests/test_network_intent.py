from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from dashboard.app import create_app
from lib.repositories import SQLiteDatabase
from lib.security import AuthManager
from lib.services.device_inventory import DeviceInventoryService
from lib.services.network_intent import (
    NetworkIntentConflict,
    NetworkIntentError,
    NetworkIntentNotFound,
    NetworkIntentService,
)
from lib.services.topology_studio import TopologyStudioService


@pytest.fixture
def network_lab(tmp_path):
    database = SQLiteDatabase(tmp_path / "network-intent.sqlite")
    database.initialize()
    now = "2026-11-23T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-1", "org", "Organization", "ACTIVE", now, now),
        )
        for project_id, slug, name in (
            ("project-1", "primary", "Primary Project"),
            ("project-2", "other", "Other Project"),
        ):
            connection.execute(
                "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (project_id, "org-1", slug, name, "ACTIVE", now, now),
            )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-1", "project-1", "Primary Lab", "gns3", 1, "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-2", "project-2", "Other Lab", "gns3", 1, "ACTIVE", now, now),
        )
    topology = TopologyStudioService(database)
    intent = NetworkIntentService(database, topology)
    profile = topology.create_profile(
        project_id="project-1", name="Primary fabric",
        scope_type="LAB", scope_id="lab-1", actor="owner",
    )
    topology_revision = topology.create_revision(
        profile["profile_id"], definition={
            "nodes": [
                {"id": "router-a", "name": "Router A", "node_type": "ROUTER", "template_id": "", "x": 100, "y": 100},
                {"id": "switch-a", "name": "Switch A", "node_type": "SWITCH", "template_id": "", "x": 300, "y": 100},
            ],
            "links": [
                {"id": "link-a", "source_node_id": "router-a", "source_adapter": 0,
                 "source_port": 0, "target_node_id": "switch-a", "target_adapter": 0, "target_port": 1},
            ],
        }, actor="owner",
    )
    device = DeviceInventoryService(database).create({
        "project_id": "project-1", "lab_id": "lab-1",
        "device_key": "router-a", "name": "Router A",
        "device_type": "ROUTER", "host": "192.0.2.10",
        "vendor": "Cisco", "model": "IOS-XE",
    }, actor="owner")
    return database, topology, intent, profile, topology_revision, device


def valid_intent(device_id: str | None = None) -> dict:
    result = {
        "schema_version": "1.0",
        "targets": [],
        "segments": [
            {"segment_id": "users", "name": "Users", "vlan_id": 20,
             "ipv4_cidr": "192.0.2.0/24", "ipv6_cidr": "2001:db8:1::/64"},
        ],
        "interfaces": [
            {"logical_node_id": "router-a", "name": "eth0", "admin_state": "UP",
             "mode": "ROUTED", "addresses": ["192.0.2.1/24", "2001:db8:1::1/64"]},
            {"logical_node_id": "router-a", "name": "eth1", "admin_state": "UP", "mode": "ROUTED"},
            {"logical_node_id": "router-a", "name": "eth2", "admin_state": "UP", "mode": "ROUTED"},
        ],
        "static_routes": [
            {"logical_node_id": "router-a", "destination": "198.51.100.0/24",
             "next_hop": "192.0.2.254", "interface_name": "eth0", "metric": 10},
        ],
        "ospf": [
            {"logical_node_id": "router-a", "process_id": 1, "router_id": "1.1.1.1",
             "areas": [{"area_id": "0", "networks": ["192.0.2.0/24"]}]},
        ],
        "bgp": [
            {"logical_node_id": "router-a", "local_asn": 65001, "router_id": "1.1.1.1",
             "neighbors": [{"address": "192.0.2.2", "remote_asn": 65002, "description": "Transit"}]},
        ],
        "aggregations": [
            {"logical_node_id": "router-a", "name": "port-channel1",
             "protocol": "LACP", "mode": "ACTIVE", "members": ["eth1", "eth2"]},
        ],
        "firewall_zones": [
            {"logical_node_id": "router-a", "zone_id": "inside", "name": "Inside", "interfaces": ["eth0"]},
            {"logical_node_id": "router-a", "zone_id": "outside", "name": "Outside", "interfaces": ["eth1"]},
        ],
        "firewall_rules": [
            {"logical_node_id": "router-a", "rule_id": "allow-web", "name": "Allow web",
             "source_zone_id": "inside", "destination_zone_id": "outside",
             "action": "ALLOW", "protocol": "TCP",
             "source_cidrs": ["192.0.2.0/24"], "destination_cidrs": ["198.51.100.0/24"],
             "destination_ports": [{"start": 80, "end": 80}, {"start": 443, "end": 443}]},
        ],
        "service_references": [],
        "linux_bridges": [
            {"logical_node_id": "router-a", "name": "br-lan", "members": ["eth1", "eth2"]},
        ],
        "linux_vlan_interfaces": [
            {"logical_node_id": "router-a", "name": "eth0.20", "parent_interface": "eth0", "vlan_id": 20},
        ],
    }
    if device_id:
        result["targets"] = [{"logical_node_id": "router-a", "device_id": device_id}]
    return result


def _create_capability_report(intent_service, device, *, unsupported=(), observed_at=None):
    required = {
        "addressing.ipv4", "addressing.ipv6", "interfaces.admin_state",
        "routing.static_ipv4", "routing.ospf", "routing.bgp",
        "aggregation.lacp", "firewall.zones", "firewall.basic_acl",
        "linux.bridge", "linux.vlan_interface",
    }
    capabilities = {
        feature: {"status": "UNSUPPORTED" if feature in unsupported else "SUPPORTED",
                  "constraints": {}}
        for feature in required
    }
    return intent_service.record_capability_report(
        project_id="project-1", device_id=device["device_id"],
        provider_id="gns3", platform="Cisco IOS XE", software_version="17.12",
        adapter_name="gns3-capability-probe", adapter_version="1.0",
        capabilities=capabilities, actor="adapter",
        source_type="PROVIDER_ADAPTER", observed_at=observed_at or datetime.now(timezone.utc).isoformat(),
    )


def test_intent_schema_is_canonical_and_covers_the_initial_network_domain():
    value = valid_intent()
    first = NetworkIntentService.normalize_definition(value)
    reversed_value = copy.deepcopy(value)
    reversed_value["segments"].reverse()
    reversed_value["interfaces"].reverse()
    second = NetworkIntentService.normalize_definition(reversed_value)
    assert first == second
    assert first["schema_version"] == "1.0"
    assert first["segments"][0]["vlan_id"] == 20
    assert first["interfaces"][0]["addresses"] == ["192.0.2.1/24", "2001:db8:1::1/64"]
    assert first["ospf"][0]["process_id"] == 1
    assert first["bgp"][0]["local_asn"] == 65001
    assert first["aggregations"][0]["protocol"] == "LACP"
    assert first["firewall_rules"][0]["destination_ports"][1]["start"] == 443
    assert first["linux_vlan_interfaces"][0]["vlan_id"] == 20


@pytest.mark.parametrize(("mutate", "message"), [
    (lambda value: value.update(schema_version="2.0"), "schema_version"),
    (lambda value: value.update(unmodelled_cli="router bgp 65001"), "unsupported fields"),
    (lambda value: value["segments"][0].update(vlan_id=4095), "1 to 4094"),
    (lambda value: value["segments"][0].update(ipv4_cidr="192.0.2.7/24"), "canonical IPv4"),
    (lambda value: value["interfaces"][0].update(mode="ACCESS"), "ACCESS mode requires access_vlan_id"),
    (lambda value: value["interfaces"][0].update(access_vlan_id=10), "ROUTED mode"),
    (lambda value: value["static_routes"][0].update(next_hop="2001:db8::1"), "same IP family"),
    (lambda value: value["bgp"][0].update(local_asn=0), "1 to 4294967295"),
    (lambda value: value["firewall_rules"][0].update(action="PERMIT"), "ALLOW or DENY"),
    (lambda value: value["aggregations"][0].update(members=["eth1"]), "at least two"),
    (lambda value: value.update(password="inline-secret"), "inline secret-like"),
])
def test_invalid_network_intent_is_rejected(mutate, message):
    value = valid_intent()
    mutate(value)
    with pytest.raises(NetworkIntentError, match=message):
        NetworkIntentService.normalize_definition(value)


def test_profile_and_revision_pin_the_immutable_topology_hash(network_lab):
    database, topology, service, topology_profile, topology_revision, _device = network_lab
    profile = service.create_profile(
        project_id="project-1", topology_profile_id=topology_profile["profile_id"],
        name="Primary network intent", actor="owner",
    )
    revision = service.create_revision(
        profile["profile_id"], topology_revision_id=topology_revision["revision_id"],
        definition=valid_intent(), actor="owner",
    )
    assert profile["scope_type"] == "LAB"
    assert profile["scope_id"] == "lab-1"
    assert revision["status"] == "DRAFT"
    assert revision["topology_content_sha256"] == topology_revision["content_sha256"]
    canonical = json.dumps(revision["definition"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert revision["intent_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="content is immutable"):
            connection.execute(
                "UPDATE network_intent_revisions SET definition_json='{}' WHERE revision_id=?",
                (revision["revision_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="ownership and identity are immutable"):
            connection.execute(
                "UPDATE network_intent_profiles SET topology_profile_id='other-topology' WHERE profile_id=?",
                (profile["profile_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            connection.execute(
                "DELETE FROM network_intent_revisions WHERE revision_id=?",
                (revision["revision_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="observations are immutable"):
            connection.execute(
                "UPDATE device_capability_reports SET platform='Other' WHERE report_id='missing'",
            )


def test_capability_validation_requires_real_adapter_observation_and_blocks_unsupported(network_lab):
    _database, topology, service, topology_profile, topology_revision, device = network_lab
    profile = service.create_profile(
        project_id="project-1", topology_profile_id=topology_profile["profile_id"],
        name="Capability intent", actor="owner",
    )
    value = valid_intent(device["device_id"])
    structural = service.validate(
        "project-1", topology_revision["revision_id"], value,
        profile_id=profile["profile_id"], evaluate_capabilities=False,
    )
    assert structural["valid"] is True
    assert structural["ready_for_compilation"] is False
    assert structural["capability_status"] == "NOT_EVALUATED"

    missing = service.validate(
        "project-1", topology_revision["revision_id"], value,
        profile_id=profile["profile_id"], evaluate_capabilities=True,
    )
    assert missing["valid"] is False
    assert missing["capability_status"] == "UNKNOWN"
    assert any(item["code"] == "CAPABILITY_REPORT_MISSING" for item in missing["diagnostics"])

    _create_capability_report(service, device)
    compatible = service.validate(
        "project-1", topology_revision["revision_id"], value,
        profile_id=profile["profile_id"], evaluate_capabilities=True,
    )
    assert compatible["valid"] is True
    assert compatible["ready_for_compilation"] is True
    assert compatible["capability_status"] == "COMPATIBLE"

    unsupported = _create_capability_report(service, device, unsupported={"routing.ospf"}, observed_at=(datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat())
    assert unsupported["report_id"]
    blocked = service.validate(
        "project-1", topology_revision["revision_id"], value,
        profile_id=profile["profile_id"], evaluate_capabilities=True,
    )
    assert blocked["valid"] is False
    assert blocked["capability_status"] == "INCOMPATIBLE"
    assert any(
        item["code"] == "CAPABILITY_UNSUPPORTED" and item["feature_id"] == "routing.ospf"
        for item in blocked["diagnostics"]
    )


def test_stale_capability_observations_are_unknown_and_block_readiness(network_lab):
    _database, _topology, service, topology_profile, topology_revision, device = network_lab
    profile = service.create_profile(
        project_id="project-1", topology_profile_id=topology_profile["profile_id"],
        name="Stale observation intent", actor="owner",
    )
    value = valid_intent(device["device_id"])
    _create_capability_report(
        service, device, observed_at="2026-11-01T00:00:00+00:00",
    )
    result = service.validate(
        "project-1", topology_revision["revision_id"], value,
        profile_id=profile["profile_id"], evaluate_capabilities=True,
    )
    assert result["valid"] is False
    assert result["ready_for_compilation"] is False
    assert result["capability_status"] == "UNKNOWN"
    assert any(item["code"] == "CAPABILITY_REPORT_STALE" for item in result["diagnostics"])


def test_published_topology_and_current_capabilities_are_required_to_publish_intent(network_lab):
    database, topology, service, topology_profile, topology_revision, device = network_lab
    profile = service.create_profile(
        project_id="project-1", topology_profile_id=topology_profile["profile_id"],
        name="Publish network intent", actor="owner",
    )
    revision = service.create_revision(
        profile["profile_id"], topology_revision_id=topology_revision["revision_id"],
        definition=valid_intent(device["device_id"]), actor="owner",
    )
    with pytest.raises(NetworkIntentConflict, match="published topology"):
        service.publish(profile["profile_id"], revision["revision_id"], actor="owner")

    topology.publish(topology_profile["profile_id"], topology_revision["revision_id"], actor="owner")
    _create_capability_report(service, device)
    published = service.publish(profile["profile_id"], revision["revision_id"], actor="owner")
    assert published["status"] == "PUBLISHED"

    with pytest.raises(NetworkIntentConflict, match="only draft"):
        service.publish(profile["profile_id"], revision["revision_id"], actor="owner")

    rolled_back = service.rollback(profile["profile_id"], published["revision_id"], actor="owner")
    assert rolled_back["status"] == "DRAFT"
    assert rolled_back["parent_revision_id"] == published["revision_id"]
    assert rolled_back["definition"] == published["definition"]


def test_project_and_lab_scope_boundaries_are_enforced(network_lab):
    _database, topology, service, topology_profile, topology_revision, device = network_lab
    with pytest.raises(NetworkIntentNotFound, match="topology profile not found"):
        service.create_profile(
            project_id="project-2", topology_profile_id=topology_profile["profile_id"],
            name="Cross-project", actor="owner",
        )
    foreign_device = DeviceInventoryService(_database).create({
        "project_id": "project-2", "lab_id": "lab-2",
        "device_key": "other-router", "name": "Other Router",
        "device_type": "ROUTER", "host": "198.51.100.10",
    }, actor="owner")
    value = valid_intent(foreign_device["device_id"])
    with pytest.raises(NetworkIntentNotFound, match="target Device not found"):
        service.create_revision(
            service.create_profile(project_id="project-1", topology_profile_id=topology_profile["profile_id"],
                                   name="Scope check", actor="owner")["profile_id"],
            topology_revision_id=topology_revision["revision_id"], definition=value, actor="owner",
        )
    with pytest.raises(NetworkIntentNotFound, match="Device not found"):
        service.record_capability_report(
            project_id="project-1", device_id=foreign_device["device_id"],
            provider_id="gns3", platform="Cisco", software_version="17",
            adapter_name="probe", adapter_version="1", capabilities={
                "routing.ospf": {"status": "SUPPORTED"},
            }, actor="adapter",
        )


def test_capability_reports_reject_unknown_features_and_invalid_provenance(network_lab):
    _database, _topology, service, _profile, _topology_revision, device = network_lab
    with pytest.raises(NetworkIntentError, match="unknown feature IDs"):
        service.record_capability_report(
            project_id="project-1", device_id=device["device_id"],
            provider_id="gns3", platform="Cisco", software_version="17",
            adapter_name="probe", adapter_version="1",
            capabilities={"routing.magic": {"status": "SUPPORTED"}}, actor="adapter",
        )
    with pytest.raises(NetworkIntentError, match="provider_id is required"):
        service.record_capability_report(
            project_id="project-1", device_id=device["device_id"],
            platform="Linux", software_version="6.8", adapter_name="probe",
            adapter_version="1", capabilities={"linux.bridge": {"status": "SUPPORTED"}},
            actor="adapter", source_type="PROVIDER_ADAPTER",
        )


def test_api_profiles_revisions_validation_and_device_capability_read(network_lab):
    database, _topology, service, topology_profile, topology_revision, device = network_lab
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()
    created = client.post(
        "/api/v1/network-intent/profiles",
        headers={"Idempotency-Key": "network-intent-profile-001"},
        json={"project_id": "project-1", "topology_profile_id": topology_profile["profile_id"],
              "name": "API intent"},
    )
    assert created.status_code == 201
    profile = created.get_json()["data"]
    retry = client.post(
        "/api/v1/network-intent/profiles",
        headers={"Idempotency-Key": "network-intent-profile-001"},
        json={"project_id": "project-1", "topology_profile_id": topology_profile["profile_id"],
              "name": "API intent"},
    )
    assert retry.status_code == 201
    assert retry.get_json()["data"]["profile_id"] == profile["profile_id"]

    created_revision = client.post(
        f"/api/v1/network-intent/profiles/{profile['profile_id']}/revisions",
        headers={"Idempotency-Key": "network-intent-revision-001"},
        json={"topology_revision_id": topology_revision["revision_id"], "definition": valid_intent()},
    )
    assert created_revision.status_code == 201
    revision = created_revision.get_json()["data"]
    validated = client.post(
        "/api/v1/network-intent/validate",
        json={"project_id": "project-1", "profile_id": profile["profile_id"],
              "topology_revision_id": topology_revision["revision_id"], "definition": revision["definition"]},
    )
    assert validated.status_code == 200
    assert validated.get_json()["data"]["valid"] is True
    assert validated.get_json()["data"]["ready_for_compilation"] is False

    _create_capability_report(service, device)
    reports = client.get(f"/api/v1/devices/{device['device_id']}/capability-reports")
    assert reports.status_code == 200
    assert reports.get_json()["data"]["items"][0]["device_id"] == device["device_id"]
