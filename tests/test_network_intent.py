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
from lib.network_config.adapters import (
    AristaEosAdapter,
    CiscoIosXeAdapter,
    JuniperJunosAdapter,
    LinuxFrrAdapter,
    PaloAltoPanOsAdapter,
)
from lib.network_config.registry import AdapterResolutionError, NetworkConfigAdapterRegistry
from lib.services.network_intent_compiler import (
    NetworkIntentCompilationError,
    NetworkIntentCompilerService,
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


def test_capability_validation_requires_real_adapter_observation_and_blocks_unsupported(network_lab):
    database, topology, service, topology_profile, topology_revision, device = network_lab
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

    report = _create_capability_report(service, device)
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="observations are immutable"):
            connection.execute(
                "UPDATE device_capability_reports SET platform='Other' WHERE report_id=?",
                (report["report_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="history cannot be deleted"):
            connection.execute(
                "DELETE FROM device_capability_reports WHERE report_id=?",
                (report["report_id"],),
            )
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


def _published_cisco_compiler_revision(network_lab, *, include_linux=False):
    database, topology, service, topology_profile, topology_revision, device = network_lab
    topology.publish(topology_profile["profile_id"], topology_revision["revision_id"], actor="owner")
    _create_capability_report(service, device)
    profile = service.create_profile(
        project_id="project-1", topology_profile_id=topology_profile["profile_id"],
        name="Compiler intent", actor="owner",
    )
    definition = valid_intent(device["device_id"])
    if not include_linux:
        definition["linux_bridges"] = []
        definition["linux_vlan_interfaces"] = []
    names = {
        "eth0": "GigabitEthernet0/0",
        "eth1": "GigabitEthernet0/1",
        "eth2": "GigabitEthernet0/2",
    }
    for interface in definition["interfaces"]:
        interface["name"] = names[interface["name"]]
    for route in definition["static_routes"]:
        route["interface_name"] = names[route["interface_name"]]
    for aggregation in definition["aggregations"]:
        aggregation["name"] = "Port-channel1"
        aggregation["members"] = [names[item] for item in aggregation["members"]]
    for zone in definition["firewall_zones"]:
        zone["interfaces"] = [names[item] for item in zone["interfaces"]]
    for bridge in definition["linux_bridges"]:
        bridge["members"] = [names[item] for item in bridge["members"]]
    for vlan in definition["linux_vlan_interfaces"]:
        vlan["parent_interface"] = names[vlan["parent_interface"]]
    revision = service.create_revision(
        profile["profile_id"], topology_revision_id=topology_revision["revision_id"],
        definition=definition, actor="owner",
    )
    published = service.publish(profile["profile_id"], revision["revision_id"], actor="owner")
    return database, service, profile, published, device


def test_network_config_registry_recognizes_only_supported_observed_platforms():
    registry = NetworkConfigAdapterRegistry()
    cases = (
        ({"vendor": "Ubuntu", "model": "Server"}, {"platform": "Linux/FRR", "software_version": "9.1"}, "linux_frr"),
        ({"vendor": "Cisco", "model": "IOS-XE"}, {"platform": "Cisco IOS XE", "software_version": "17.12"}, "cisco_iosxe"),
        ({"vendor": "Arista", "model": "7050X"}, {"platform": "Arista EOS", "software_version": "4.32.1F"}, "arista_eos"),
        ({"vendor": "Juniper Networks", "model": "SRX345"}, {"platform": "Juniper Junos", "software_version": "22.4R3.8"}, "juniper_junos"),
        ({"vendor": "Palo Alto Networks", "model": "PA-VM"}, {"platform": "Palo Alto Networks PAN-OS", "software_version": "11.2.3"}, "paloalto_panos"),
    )
    for device, report, expected in cases:
        assert registry.resolve(device, report).descriptor.adapter_id == expected
    with pytest.raises(AdapterResolutionError) as mismatch:
        registry.resolve(
            {"vendor": "Arista", "model": "7050X"},
            {"platform": "Cisco IOS XE", "software_version": "17.12"},
        )
    assert mismatch.value.code == "DEVICE_VENDOR_PLATFORM_MISMATCH"
    with pytest.raises(AdapterResolutionError) as unsupported:
        registry.resolve(
            {"vendor": "Cisco", "model": "IOS-XE"},
            {"platform": "Cisco IOS XE", "software_version": "18.1"},
        )
    assert unsupported.value.code == "SOFTWARE_VERSION_UNSUPPORTED"


def test_network_config_adapter_feature_boundaries_are_explicit():
    juniper = JuniperJunosAdapter()
    assert "firewall.zones" in juniper.supported_features({"model": "SRX345"})
    assert "firewall.zones" not in juniper.supported_features({"model": "MX204"})
    arista = AristaEosAdapter()
    assert "routing.bgp" in arista.supported_features({"model": "7050X"})
    assert "firewall.zones" not in arista.supported_features({"model": "7050X"})
    pan = PaloAltoPanOsAdapter()
    assert "firewall.basic_acl" in pan.supported_features({"model": "PA-VM"})
    assert "vlans.access" not in pan.supported_features({"model": "PA-VM"})
    linux = LinuxFrrAdapter()
    assert "linux.bridge" in linux.supported_features({"model": "Ubuntu"})
    assert "services.dhcp" not in linux.supported_features({"model": "Ubuntu"})


def test_iosxe_compiler_is_deterministic_revision_bound_and_supports_baseline_diff(network_lab):
    database, service, profile, revision, device = _published_cisco_compiler_revision(network_lab)
    compiler = NetworkIntentCompilerService(database, service)
    first = compiler.compile_revision(profile["profile_id"], revision["revision_id"])
    assert first["status"] == "COMPILED"
    assert first["compile_only"] is True
    assert first["application_performed"] is False
    assert first["ready_for_application"] is False
    assert first["intent_sha256"] == revision["intent_sha256"]
    assert first["topology_content_sha256"] == revision["topology_content_sha256"]
    assert first["adapters"][0]["adapter_id"] == "cisco_iosxe"
    assert len(first["artifacts"]) == 1
    content = first["artifacts"][0]["content"]
    assert "router bgp 65001" in content
    assert "channel-group 1 mode active" in content
    assert "zone-pair security" in content
    assert "neighbor 192.0.2.2 remote-as 65002" in content
    assert "ip address 192.0.2.1 255.255.255.0" in content
    assert "ip route 198.51.100.0 255.255.255.0 192.0.2.254 10" in content
    assert first["artifacts"][0]["sha256"] == hashlib.sha256(content.encode()).hexdigest()

    repeated = compiler.compile_revision(profile["profile_id"], revision["revision_id"])
    assert repeated["compilation_id"] == first["compilation_id"]
    assert [item["sha256"] for item in repeated["artifacts"]] == [item["sha256"] for item in first["artifacts"]]

    baseline = {item["path"]: item["content"] for item in first["artifacts"]}
    compared = compiler.compile_revision(
        profile["profile_id"], revision["revision_id"], baseline_artifacts=baseline,
    )
    assert compared["compilation_id"] == first["compilation_id"]
    assert compared["change_summary"] == {"new": 0, "changed": 0, "unchanged": 1}
    assert compared["artifacts"][0]["change_type"] == "UNCHANGED"
    assert compared["artifacts"][0]["diff"] == ""


def test_compiler_rejects_draft_revisions_and_never_returns_partial_vendor_output(network_lab):
    database, _topology, service, topology_profile, topology_revision, device = network_lab
    _create_capability_report(service, device)
    profile = service.create_profile(
        project_id="project-1", topology_profile_id=topology_profile["profile_id"],
        name="Draft compiler intent", actor="owner",
    )
    draft = service.create_revision(
        profile["profile_id"], topology_revision_id=topology_revision["revision_id"],
        definition=valid_intent(device["device_id"]), actor="owner",
    )
    compiler = NetworkIntentCompilerService(database, service)
    result = compiler.compile_revision(profile["profile_id"], draft["revision_id"])
    assert result["status"] == "BLOCKED"
    assert result["artifacts"] == []
    assert result["diagnostics"][0]["code"] == "NETWORK_INTENT_REVISION_NOT_PUBLISHED"


def test_cisco_compiler_blocks_linux_only_features_without_emitting_partial_artifacts(network_lab):
    database, service, profile, revision, _device = _published_cisco_compiler_revision(
        network_lab, include_linux=True,
    )
    result = NetworkIntentCompilerService(database, service).compile_revision(
        profile["profile_id"], revision["revision_id"],
    )
    assert result["status"] == "BLOCKED"
    assert result["artifacts"] == []
    unsupported = {item.get("feature_id") for item in result["diagnostics"] if item["code"] == "ADAPTER_FEATURE_UNSUPPORTED"}
    assert {"linux.bridge", "linux.vlan_interface"} <= unsupported


def test_iosxe_adapter_rejects_cli_injection_in_interface_names_and_bgp_descriptions():
    adapter = CiscoIosXeAdapter()
    base = {
        "logical_node_id": "router-a", "schema_version": "1.0", "segments": [],
        "interfaces": [], "static_routes": [], "ospf": [], "aggregations": [],
        "firewall_zones": [], "firewall_rules": [], "service_references": [],
        "linux_bridges": [], "linux_vlan_interfaces": [],
        "bgp": [{
            "logical_node_id": "router-a", "local_asn": 65001, "router_id": "1.1.1.1",
            "neighbors": [{"address": "192.0.2.2", "remote_asn": 65002, "description": "Transit\nend"}],
        }],
    }
    with pytest.raises(Exception, match="description"):
        adapter.compile_target({"name": "Router A"}, base)
    injected = dict(base)
    injected["bgp"] = []
    injected["interfaces"] = [{
        "name": "GigabitEthernet0/0\nend", "mode": "ROUTED",
        "addresses": [], "admin_state": "UP",
    }]
    with pytest.raises(Exception, match="Interface name"):
        adapter.compile_target({"name": "Router A"}, injected)


def test_compiler_baseline_rejects_traversal_and_secret_bearing_text():
    with pytest.raises(NetworkIntentCompilationError, match="confined relative path"):
        NetworkIntentCompilerService._normalize_baseline({"../../etc/passwd": "root:x"})
    with pytest.raises(NetworkIntentCompilationError, match="credential or secret"):
        NetworkIntentCompilerService._normalize_baseline({"baseline.cfg": "username admin password hunter2"})


def test_linux_frr_adapter_renders_ipv6_routes_and_systemd_network_artifacts():
    adapter = LinuxFrrAdapter()
    intent = {
        "logical_node_id": "linux-router", "schema_version": "1.0", "segments": [],
        "interfaces": [{
            "name": "eth0", "admin_state": "UP", "mode": "ROUTED",
            "addresses": ["2001:db8:1::1/64"],
        }],
        "static_routes": [{
            "destination": "2001:db8:2::/64", "next_hop": "2001:db8:1::2",
            "interface_name": "eth0", "metric": 10,
        }],
        "ospf": [], "bgp": [], "aggregations": [], "firewall_zones": [],
        "firewall_rules": [], "service_references": [], "linux_bridges": [],
        "linux_vlan_interfaces": [],
    }
    files = adapter.compile_target({"name": "Linux Router"}, intent)
    assert "systemd/network/10-linux-router-eth0.network" in files
    assert "operator/link-state.sh" in files
    assert "ipv6 route 2001:db8:2::/64 2001:db8:1::2 eth0 10" in files["frr/frr.conf"]
    assert "Address=2001:db8:1::1/64" in files["systemd/network/10-linux-router-eth0.network"]


def test_arista_junos_and_panos_adapters_emit_native_output_and_block_unsupported_semantics():
    eos = AristaEosAdapter().compile_target(
        {"name": "Arista Switch"},
        {
            "logical_node_id": "switch-a", "schema_version": "1.0", "segments": [],
            "interfaces": [{"name": "Ethernet1/1", "admin_state": "UP", "mode": "ROUTED", "addresses": ["192.0.2.2/24"]}],
            "static_routes": [], "ospf": [], "bgp": [], "aggregations": [],
            "firewall_zones": [], "firewall_rules": [], "service_references": [],
            "linux_bridges": [], "linux_vlan_interfaces": [],
        },
    )["startup-config.txt"]
    assert "interface Ethernet1/1" in eos
    assert "ip address 192.0.2.2/24" in eos

    junos = JuniperJunosAdapter().compile_target(
        {"name": "Juniper Edge", "model": "MX204"},
        {
            "logical_node_id": "edge-a", "schema_version": "1.0", "segments": [],
            "interfaces": [{"name": "ge-0/0/0", "admin_state": "UP", "mode": "ROUTED", "addresses": ["2001:db8:1::1/64"]}],
            "static_routes": [{"destination": "2001:db8:2::/64", "next_hop": "2001:db8:1::2", "metric": 1}],
            "ospf": [], "bgp": [], "aggregations": [], "firewall_zones": [],
            "firewall_rules": [], "service_references": [], "linux_bridges": [],
            "linux_vlan_interfaces": [],
        },
    )["candidate.set"]
    assert "set routing-options rib inet6.0 static route 2001:db8:2::/64 next-hop 2001:db8:1::2" in junos

    panos = PaloAltoPanOsAdapter().compile_target(
        {"name": "Palo Alto Edge", "model": "PA-VM"},
        {
            "logical_node_id": "pa-a", "schema_version": "1.0", "segments": [],
            "interfaces": [{"name": "ethernet1/1", "admin_state": "UP", "mode": "ROUTED", "addresses": ["2001:db8:1::1/64"]}],
            "static_routes": [{"destination": "2001:db8:2::/64", "next_hop": "2001:db8:1::2", "metric": 10}],
            "ospf": [], "bgp": [], "aggregations": [], "firewall_zones": [],
            "firewall_rules": [], "service_references": [], "linux_bridges": [],
            "linux_vlan_interfaces": [],
        },
    )["panos-set-commands.txt"]
    assert "routing-table ipv6 static-route" in panos
    assert "nexthop ipv6-address 2001:db8:1::2" in panos

    with pytest.raises(ValueError, match="OSPFv3"):
        AristaEosAdapter().compile_target(
            {"name": "Arista Switch"},
            {
                "logical_node_id": "switch-a", "schema_version": "1.0", "segments": [],
                "interfaces": [{"name": "Ethernet1/1", "admin_state": "UP", "mode": "ROUTED", "addresses": ["2001:db8:1::1/64"]}],
                "static_routes": [], "ospf": [{"process_id": 1, "router_id": "1.1.1.1", "areas": [{"area_id": "0", "networks": ["2001:db8:1::/64"]}]}],
                "bgp": [], "aggregations": [], "firewall_zones": [], "firewall_rules": [],
                "service_references": [], "linux_bridges": [], "linux_vlan_interfaces": [],
            },
        )


def test_compile_api_returns_registered_adapters_and_preview_only_artifacts(network_lab):
    database, service, profile, revision, _device = _published_cisco_compiler_revision(network_lab)
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()
    catalog = client.get("/api/v1/network-intent/compiler/adapters?project_id=project-1")
    assert catalog.status_code == 200
    adapter_ids = {item["adapter_id"] for item in catalog.get_json()["data"]["items"]}
    assert adapter_ids == {"linux_frr", "cisco_iosxe", "arista_eos", "juniper_junos", "paloalto_panos"}

    result = client.post(
        f"/api/v1/network-intent/profiles/{profile['profile_id']}/revisions/{revision['revision_id']}/compile",
        json={},
    )
    assert result.status_code == 200
    data = result.get_json()["data"]
    assert data["status"] == "COMPILED"
    assert data["compile_only"] is True
    assert data["application_performed"] is False
    assert data["ready_for_application"] is False


def test_frr_and_vendor_adapter_lacp_modes_and_family_mismatch_are_not_silently_translated():
    eos_intent = {
        "logical_node_id": "switch-a", "schema_version": "1.0", "segments": [],
        "interfaces": [
            {"name": "Ethernet1/1", "admin_state": "UP", "mode": "ROUTED", "addresses": []},
            {"name": "Ethernet1/2", "admin_state": "UP", "mode": "ROUTED", "addresses": []},
        ],
        "static_routes": [], "ospf": [], "bgp": [],
        "aggregations": [{
            "name": "Port-Channel7", "protocol": "LACP", "mode": "PASSIVE",
            "members": ["Ethernet1/1", "Ethernet1/2"],
        }],
        "firewall_zones": [], "firewall_rules": [], "service_references": [],
        "linux_bridges": [], "linux_vlan_interfaces": [],
    }
    eos = AristaEosAdapter().compile_target({"name": "EOS"}, eos_intent)["startup-config.txt"]
    assert "channel-group 7 mode passive" in eos

    linux_intent = {
        "logical_node_id": "host-a", "schema_version": "1.0", "segments": [],
        "interfaces": [
            {"name": "eth0", "admin_state": "UP", "mode": "ROUTED", "addresses": ["192.0.2.1/24"]},
            {"name": "eth1", "admin_state": "UP", "mode": "ROUTED", "addresses": []},
        ],
        "static_routes": [], "ospf": [], "bgp": [], "aggregations": [],
        "firewall_zones": [
            {"zone_id": "inside", "name": "Inside", "interfaces": ["eth0"]},
            {"zone_id": "outside", "name": "Outside", "interfaces": ["eth1"]},
        ],
        "firewall_rules": [{
            "rule_id": "mixed-family", "source_zone_id": "inside", "destination_zone_id": "outside",
            "action": "ALLOW", "protocol": "TCP", "source_cidrs": ["192.0.2.0/24"],
            "destination_cidrs": ["2001:db8::/64"], "destination_ports": [{"start": 443, "end": 443}],
        }],
        "service_references": [], "linux_bridges": [], "linux_vlan_interfaces": [],
    }
    with pytest.raises(ValueError, match="different address families"):
        LinuxFrrAdapter().compile_target({"name": "Linux"}, linux_intent)
