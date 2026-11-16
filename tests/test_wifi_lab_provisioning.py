from __future__ import annotations

from lib.services.wifi_lab_provisioning import WiFiLabProvisioningService


def node(name, node_id, *, status="stopped", ports=()):
    return {
        "name": name, "node_id": node_id, "status": status,
        "ports": [{"adapter_number": a, "port_number": p} for a, p in ports],
    }


def test_wifi_lab_plan_requires_reference_nodes_and_client_management_port():
    nodes = [
        node("frr-router", "frr", ports=[(0, 0)]),
        node("hostapd-ap", "ap", ports=[(0, 0)]),
        node("wifi-client", "client", ports=[(0, 0)]),
        node("monitor", "monitor", ports=[(0, 0)]),
        node("Switch1", "switch", ports=[(0, 0)]),
    ]
    plan = WiFiLabProvisioningService.analyze_snapshot(
        project_id="gns3-project", project_status="opened", nodes=nodes, links=[],
    )
    assert not plan["can_apply"]
    assert "CLIENT_MANAGEMENT_ADAPTER_MISSING" in {item["code"] for item in plan["conflicts"]}
    assert plan["safety"]["deletes_resources"] is False
    assert plan["safety"]["stops_nodes"] is False


def test_wifi_lab_plan_selects_free_switch_port_without_rewiring_existing_links():
    nodes = [
        node("frr-router", "frr", ports=[(0, 0)]),
        node("hostapd-ap", "ap", ports=[(0, 0)]),
        node("wifi-client", "client", ports=[(0, 0), (1, 0)]),
        node("monitor", "monitor", ports=[(0, 0)]),
        node("Switch1", "switch", ports=[(0, 0), (0, 1)]),
    ]
    links = [{
        "link_id": "existing-management",
        "nodes": [
            {"node_id": "switch", "adapter_number": 0, "port_number": 0},
            {"node_id": "frr", "adapter_number": 0, "port_number": 0},
        ],
    }]
    plan = WiFiLabProvisioningService.analyze_snapshot(
        project_id="gns3-project", project_status="opened", nodes=nodes, links=links,
    )
    assert plan["can_apply"]
    assert plan["management_link"]["status"] == "MISSING"
    assert plan["management_link"]["switch_port"] == 1
    assert plan["mutations"]["create_management_link"] is True
    assert plan["safety"]["disconnects_or_rewires_links"] is False


def test_wifi_lab_plan_detects_existing_client_management_link_and_started_nodes():
    nodes = [
        node("frr-router", "frr", status="started", ports=[(0, 0)]),
        node("hostapd-ap", "ap", status="started", ports=[(0, 0)]),
        node("wifi-client", "client", status="started", ports=[(0, 0), (1, 0)]),
        node("monitor", "monitor", status="started", ports=[(0, 0)]),
        node("Switch1", "switch", status="started", ports=[(0, 0)]),
    ]
    links = [{
        "link_id": "mgmt",
        "nodes": [
            {"node_id": "client", "adapter_number": 1, "port_number": 0},
            {"node_id": "switch", "adapter_number": 0, "port_number": 0},
        ],
    }]
    plan = WiFiLabProvisioningService.analyze_snapshot(
        project_id="gns3-project", project_status="opened", nodes=nodes, links=links,
    )
    assert plan["can_apply"]
    assert plan["management_link"]["status"] == "PRESENT"
    assert plan["nodes_to_start"] == []
    assert plan["mutations"]["create_management_link"] is False


def test_wifi_lab_plan_fails_closed_for_missing_nodes_and_closed_project():
    nodes = [node("wifi-client", "client", ports=[(0, 0), (1, 0)])]
    plan = WiFiLabProvisioningService.analyze_snapshot(
        project_id="gns3-project", project_status="closed", nodes=nodes, links=[],
    )
    assert plan["missing_nodes"] == ["frr-router", "hostapd-ap", "monitor"]
    assert not plan["can_apply"]
    assert {item["code"] for item in plan["conflicts"]} >= {
        "GNS3_PROJECT_NOT_OPEN", "MANAGEMENT_LINK_REQUIRES_OPERATOR",
    }
