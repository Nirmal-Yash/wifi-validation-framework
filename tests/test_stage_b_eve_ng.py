from __future__ import annotations

import pytest

from lib.providers import EVENGProvider, EVENGProviderError, ProviderRegistry


class _HTTPFixture:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class EVENGFixture(EVENGProvider):
    def __init__(self, *args, **kwargs):
        self.endpoint_url = "https://192.168.1.30"
        self.username = "operator"
        self._password = "fixture-secret"
        self._http = _HTTPFixture()
        self._connected = False
        self._version = {}
        self._auth = {}
        self.calls = []
        self.node_status = 0
        self.image_list = {
            "vios-image.bin": "vios-image.bin",
            "missing-image.missing": "missing-image.missing",
        }
        self.fail_second_interface_attach = False
        self.interface_attach_count = 0
        self.deleted_networks = []

    def _request(self, method, path, *, payload=None, allow_fail=False):
        self.calls.append((method, path, payload))
        if path == "/api/auth/login":
            return {"status": "success", "code": 200}
        if path == "/api/auth":
            return {"status": "success", "data": {
                "username": "operator", "folder": "/User1", "role": "admin",
            }}
        if path == "/api/auth/logout":
            return {"status": "success", "code": 200}
        if path == "/api/status":
            return {"status": "success", "data": {
                "version": "6.2.0", "edition": "Community", "cpu": 8, "mem": 32,
            }}
        if path == "/api/folders/User1":
            return {"status": "success", "data": {
                "folders": [{"name": "Sub", "path": "/User1/Sub"}],
                "labs": [{"file": "Lab 1.unl", "path": "/User1/Lab 1.unl"}],
            }}
        if path == "/api/folders/User1/Sub":
            return {"status": "success", "data": {
                "folders": [{"name": "..", "path": "/User1"}],
                "labs": [{"file": "Nested.unl", "path": "/User1/Sub/Nested.unl"}],
            }}
        if method == "POST" and path == "/api/labs":
            return {"status": "success", "code": 200}
        if method == "GET" and path == "/api/labs/User1/New%20Lab.unl":
            return {"status": "success", "data": {"name": "New Lab", "filename": "New Lab.unl"}}
        if method == "DELETE" and path == "/api/labs/User1/Lab%201.unl":
            return {"status": "success", "code": 200}
        if path == "/api/list/templates/":
            return {"status": "success", "data": {"vios": "Cisco vIOS", "iol": "Cisco IOL"}}
        if path == "/api/list/templates/vios":
            return {"status": "success", "data": {
                "type": "qemu",
                "options": {
                    "image": {"name": "Image", "type": "list", "value": "vios-image.bin", "list": self.image_list},
                    "config": {"value": "Unconfigured"},
                    "delay": {"value": 0},
                    "icon": {"value": "Router.png"},
                    "console": {"value": "telnet"},
                    "cpu": {"value": 1},
                    "ram": {"value": 512},
                    "ethernet": {"value": 4},
                },
            }}
        if method == "GET" and path == "/api/labs/User1/Lab%201.unl/nodes":
            return {"status": "success", "data": {
                "1": {"id": 1, "name": "Router 1", "template": "vios", "status": self.node_status,
                      "image": "vios-image.bin"},
                "2": {"id": 2, "name": "Router 2", "template": "vios", "status": 0,
                      "image": "vios-image.bin"},
            }}
        if path == "/api/labs/User1/Lab%201.unl/nodes/1":
            return {"status": "success", "data": {
                "id": 1, "name": "Router 1", "template": "vios", "status": self.node_status,
            }}
        if path == "/api/labs/User1/Lab%201.unl/nodes/1/interfaces":
            return {"status": "success", "data": {
                "ethernet": [
                    {"name": "Gi0/0", "network_id": 0},
                    {"name": "Gi0/1", "network_id": 0},
                ],
                "serial": [{"name": "Se1/0", "network_id": 0}],
            }}
        if path == "/api/labs/User1/Lab%201.unl/nodes/2/interfaces":
            return {"status": "success", "data": {
                "ethernet": [{"name": "Gi0/0", "network_id": 0},
                             {"name": "Gi0/1", "network_id": 0}],
                "serial": [],
            }}
        if path == "/api/labs/User1/Lab%201.unl/topology":
            return {"status": "success", "data": [
                {"source": "node1", "source_type": "node", "source_label": "Gi0/0",
                 "destination": "network1", "destination_type": "network", "destination_label": "",
                 "type": "ethernet"},
                {"source": "node2", "source_type": "node", "source_label": "Gi0/1",
                 "destination": "network1", "destination_type": "network", "destination_label": "",
                 "type": "ethernet"},
                {"source": "node1", "source_type": "node", "source_label": "Se1/0",
                 "destination": "node2", "destination_type": "node", "destination_label": "Se1/0",
                 "type": "serial"},
            ]}
        if method == "GET" and path == "/api/labs/User1/Lab%201.unl/networks":
            return {"status": "success", "data": {
                "1": {"id": 1, "name": "Bridge1", "type": "bridge"},
            }}
        if method == "GET" and path.endswith("/nodes/1/start"):
            self.node_status = 2
            return {"status": "success", "code": 200}
        if method == "GET" and path.endswith("/nodes/1/stop"):
            self.node_status = 0
            return {"status": "success", "code": 200}
        if method == "POST" and path == "/api/labs/User1/Lab%201.unl/networks":
            return {"status": "success", "data": {"id": 7}}
        if method == "PUT" and path.endswith("/nodes/1/interfaces"):
            self.interface_attach_count += 1
            if self.fail_second_interface_attach and self.interface_attach_count == 2:
                raise EVENGProviderError("injected interface attachment failure")
            return {"status": "success", "code": 200}
        if method == "PUT" and path.endswith("/nodes/2/interfaces"):
            self.interface_attach_count += 1
            if self.fail_second_interface_attach and self.interface_attach_count == 2:
                raise EVENGProviderError("injected interface attachment failure")
            return {"status": "success", "code": 200}
        if method == "DELETE" and "/networks/" in path:
            self.deleted_networks.append(path.rsplit("/", 1)[-1])
            return {"status": "success", "code": 200}
        if method == "GET" and path.endswith("/nodes/3"):
            return {"status": "success", "data": {"id": 3, "name": "New Router", "template": "vios", "status": 0}}
        if method == "POST" and path == "/api/labs/User1/Lab%201.unl/nodes":
            return {"status": "success", "data": {"id": 3}}
        if method == "DELETE" and path.endswith("/nodes/1"):
            return {"status": "success", "code": 200}
        if method == "DELETE" and path.endswith("/networks/1"):
            self.deleted_networks.append("1")
            return {"status": "success", "code": 200}
        if allow_fail:
            return None
        raise EVENGProviderError("unexpected fixture request: " + method + " " + path)


def test_eve_ng_is_registered_independently_and_does_not_advertise_capture():
    registry = ProviderRegistry.with_stage_b(eve_ng_factory=EVENGFixture)
    descriptors = registry.list_descriptors()
    assert [item["provider_id"] for item in descriptors] == ["cml", "eve-ng", "gns3"]
    eve = next(item for item in descriptors if item["provider_id"] == "eve-ng")
    capability_ids = {item["id"] for item in eve["capabilities"]}
    assert {"projects.read", "templates.read", "topology.nodes.create",
            "topology.links.create", "topology.interfaces.read"} <= capability_ids
    assert "packet_capture.supported" not in capability_ids
    adapter = registry.create("eve-ng", "https://192.168.1.30", "operator", "transient")
    assert isinstance(adapter, EVENGFixture)


def test_eve_ng_login_folder_catalogue_lab_and_resource_observation():
    provider = EVENGFixture()
    connected = provider.connect()
    assert connected["status"] == "HEALTHY"
    assert connected["version"]["version"] == "6.2.0"
    assert provider.health_check()["status"] == "HEALTHY"
    projects = provider.list_projects()
    assert [item["project_id"] for item in projects] == [
        "/User1/Lab 1.unl", "/User1/Sub/Nested.unl",
    ]
    templates = provider.list_templates()
    assert templates[0]["template_id"] == "vios"
    assert provider.get_template_image_availability("vios")["status"] == "AVAILABLE"
    resources = provider.get_resource_availability()
    assert resources["computes"][0]["connected"] is True
    created = provider.create_lab("New Lab")
    assert created["project_id"] == "/User1/New Lab.unl"
    create_call = next(call for call in provider.calls if call[0] == "POST" and call[1] == "/api/labs")
    assert create_call[2]["path"] == "/User1"
    assert provider.delete_lab("/User1/Lab 1.unl")["deleted"] is True
    provider.disconnect()
    assert provider._http.closed is True
    assert provider._connected is False
    assert provider._password == ""


def test_eve_ng_interfaces_topology_and_bridge_link_semantics():
    provider = EVENGFixture()
    provider.connect()
    ports = provider.get_interfaces("/User1/Lab 1.unl", "1")
    assert [(item["adapter_number"], item["port_number"]) for item in ports] == [(0, 0), (0, 1), (1, 0)]
    nodes = provider.list_nodes("/User1/Lab 1.unl")
    assert nodes[0]["ports"][1]["name"] == "Gi0/1"
    links = provider.list_links("/User1/Lab 1.unl")
    bridge = next(item for item in links if item["link_id"] == "1")
    assert bridge["nodes"] == [
        {"node_id": "1", "adapter_number": 0, "port_number": 0},
        {"node_id": "2", "adapter_number": 0, "port_number": 1},
    ]
    serial = next(item for item in links if item["link_id"].startswith("direct-serial-"))
    assert serial["nodes"][0]["adapter_number"] == 1

    created = provider.create_link(
        "/User1/Lab 1.unl", source_node_id="1", source_adapter=0, source_port=0,
        target_node_id="2", target_adapter=0, target_port=1,
    )
    assert created["link_id"] == "7"
    attached = [call for call in provider.calls if call[0] == "PUT" and call[1].endswith("/interfaces")]
    assert attached[-2][2] == {"Gi0/0": "7"}
    assert attached[-1][2] == {"Gi0/1": "7"}
    with pytest.raises(EVENGProviderError, match="Ethernet interfaces only"):
        provider.create_link(
            "/User1/Lab 1.unl", source_node_id="1", source_adapter=1, source_port=0,
            target_node_id="2", target_adapter=1, target_port=0,
        )


def test_eve_ng_link_attachment_failure_rolls_back_partial_network_mutation():
    provider = EVENGFixture()
    provider.connect()
    provider.fail_second_interface_attach = True
    with pytest.raises(EVENGProviderError, match="injected"):
        provider.create_link(
            "/User1/Lab 1.unl", source_node_id="1", source_adapter=0, source_port=0,
            target_node_id="2", target_adapter=0, target_port=1,
        )
    assert "7" in provider.deleted_networks
    detach = [call for call in provider.calls if call[0] == "PUT" and call[1].endswith("/interfaces")]
    assert detach[-1][2] == {"Gi0/0": "0"}


def test_eve_ng_node_creation_uses_verified_image_and_percentage_coordinates():
    provider = EVENGFixture()
    provider.connect()
    node = provider.create_node(
        "/User1/Lab 1.unl", "vios", name="New Router", x=2500, y=7500,
    )
    assert node["node_id"] == "3"
    payload = next(call[2] for call in provider.calls
                   if call[0] == "POST" and call[1] == "/api/labs/User1/Lab%201.unl/nodes")
    assert payload["image"] == "vios-image.bin"
    assert payload["left"] == "25%" and payload["top"] == "75%"
    provider.image_list = {"bad-image.missing": "bad-image.missing"}
    assert provider.get_template_image_availability("vios")["status"] == "MISSING"
    with pytest.raises(EVENGProviderError, match="missing image"):
        provider.create_node("/User1/Lab 1.unl", "vios", name="Broken", x=0, y=0)


def test_eve_ng_node_lifecycle_requires_readback_and_direct_links_are_observed_only():
    provider = EVENGFixture()
    provider.connect()
    assert provider.get_node_state("/User1/Lab 1.unl", "1")["status"] == "STOPPED"
    assert provider.start_node("/User1/Lab 1.unl", "1")["status"] == "STARTED"
    assert provider.stop_node("/User1/Lab 1.unl", "1")["status"] == "STOPPED"
    with pytest.raises(EVENGProviderError, match="observed-only"):
        provider.delete_link("/User1/Lab 1.unl", "direct-serial-1-2")
    assert provider.delete_link("/User1/Lab 1.unl", "1")["deleted"] is True
    assert provider.capture_support()["supported"] is False


def test_eve_ng_rejects_unsafe_workspace_paths_and_invalid_credentials():
    assert EVENGProvider._path("/User1/Lab 1.unl") == "/User1/Lab 1.unl"
    for value in ("relative/Lab.unl", "/User1/../Lab.unl", "/User1/Lab", "/User1\\Lab.unl"):
        with pytest.raises(EVENGProviderError):
            EVENGProvider._path(value)
    with pytest.raises(EVENGProviderError):
        EVENGProvider._folder_path("/User1/../../etc")
