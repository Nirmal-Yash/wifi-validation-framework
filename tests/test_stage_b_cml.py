from __future__ import annotations

import pytest

from lib.providers import ProviderRegistry
from lib.providers.cml import CMLProvider, CMLProviderError
from lib.providers.http import ProviderHTTPSession, ProviderHTTPError, validate_provider_endpoint


class CMLFixture(CMLProvider):
    def __init__(self, *args, **kwargs):
        self.endpoint_url = "https://192.168.1.20"
        self.username = "operator"
        self._password = "fixture-secret"
        self._session_factory = None
        class FixtureSession:
            def __init__(self):
                self.headers = {}
                self.closed = False
            def close(self):
                self.closed = True
        class FixtureHTTP:
            def __init__(self):
                self.session = FixtureSession()
                self.closed = False
            def close(self):
                self.closed = True
                self.session.close()
        self._http = FixtureHTTP()
        self._connected = False
        self._version = {}
        self.calls = []
        self.restricted = set()

    def _request(self, method, path, *, payload=None, params=None):
        self.calls.append((method, path, payload, params))
        if path in self.restricted:
            raise CMLProviderError("provider returned HTTP 403 for " + method + " " + path)
        if path == "/api/v0/authenticate":
            return {"token": "ephemeral-token"}
        if path == "/api/v0/authentication":
            return {"username": "operator", "authenticated": True}
        if path == "/api/v0/system_information":
            return {"version": "2.10.0", "edition": "CML-Enterprise"}
        if path == "/api/v0/labs":
            if method == "POST":
                return {"id": "lab-created"}
            return [{"id": "lab-1", "lab_title": "Acceptance Lab", "state": "DEFINED"}]
        if path == "/api/v0/node_definitions":
            return [
                {"id": "iosv", "description": "IOSv", "device_type": "router",
                 "image_definitions": ["refplat-iosv"]},
            ]
        if path == "/api/v0/system/compute_hosts":
            return [{"id": "compute-1", "hostname": "cml-compute", "state": "READY"}]
        if path == "/api/v0/licensing":
            return {"status": "AUTHORIZED", "product": "CML"}
        if path == "/api/v0/node_definitions/iosv/image_definitions":
            return [{"id": "refplat-iosv", "name": "IOSv"}]
        if path == "/api/v0/labs/lab-1/nodes":
            if method == "POST":
                return {"id": "node-created"}
            return [{"id": "node-1", "label": "Router 1", "node_definition": "iosv",
                     "state": "BOOTED", "interfaces": [{"id": "0", "label": "GigabitEthernet0"}]}]
        if path == "/api/v0/labs/lab-1/links":
            if method == "POST":
                return {"id": "link-created"}
            return [{"id": "link-1", "n1": "node-1", "i1": "0",
                     "n2": "node-2", "i2": "1"}]
        if path == "/api/v0/labs/lab-1/topology":
            return {"nodes": [], "links": []}
        if path == "/api/v0/labs/lab-1/nodes/node-1":
            return {"id": "node-1", "label": "Router 1", "node_definition": "iosv",
                    "state": "BOOTED"}
        if path == "/api/v0/labs/lab-1/nodes/node-1/interfaces":
            return [{"id": "0", "label": "GigabitEthernet0"}]
        if path == "/api/v0/labs/lab-1/nodes/node-2/interfaces":
            return [{"id": "1", "label": "GigabitEthernet1"}]
        if path.endswith("/nodes/node-created"):
            return {"id": "node-created", "state": "DEFINED"}
        return None


def test_cml_registry_uses_independent_adapter_and_full_shared_contract():
    registry = ProviderRegistry.with_cml(cml_factory=CMLFixture)
    descriptor = registry.descriptor("cml")
    adapter = registry.create("cml", "https://192.168.1.20", "operator", "fixture-secret")
    assert descriptor.name == "Cisco Modeling Labs"
    assert adapter.provider_id == "cml"
    assert all(callable(getattr(adapter, name, None)) for name in registry.REQUIRED_METHODS)


def test_cml_auth_catalogue_compute_licensing_and_image_discovery():
    provider = CMLFixture()
    connected = provider.connect()
    assert connected["status"] == "HEALTHY"
    assert connected["version"]["version"] == "2.10.0"
    assert provider.health_check()["status"] == "HEALTHY"
    assert provider.list_projects() == [{
        "project_id": "lab-1", "name": "Acceptance Lab", "status": "DEFINED",
    }]
    templates = provider.list_templates()
    assert templates[0]["template_id"] == "iosv"
    resources = provider.get_resource_availability()
    assert resources["computes"][0]["connected"] is True
    assert resources["licensing"]["status"] == "AUTHORIZED"
    image = provider.get_template_image_availability("iosv")
    assert image["status"] == "UNKNOWN"
    assert image["required_images"] == ["refplat-iosv"]
    assert image["available_images"] == []
    assert image["image_definitions_registered"] == ["refplat-iosv"]
    assert provider.capture_support()["supported"] is False
    assert "packet_capture.supported" not in {item["id"] for item in provider.get_capabilities()}
    assert provider.create_lab("New Lab")["project_id"] == "lab-created"
    assert provider.delete_lab("lab-created") == {"project_id": "lab-created", "deleted": True}
    provider.disconnect()
    assert provider._connected is False


def test_cml_topology_translation_node_link_and_state_readback():
    provider = CMLFixture()
    provider.connect()
    assert provider.list_nodes("lab-1")[0]["status"] == "STARTED"
    interfaces = provider.get_interfaces("lab-1", "node-1")
    assert interfaces[0]["port_number"] == 0
    assert provider.get_node_state("lab-1", "node-1")["status"] == "STARTED"
    node = provider.create_node("lab-1", "iosv", name="Router New", x=20, y=30)
    assert node["node_id"] == "node-created"
    link = provider.create_link(
        "lab-1", source_node_id="node-1", source_adapter=0, source_port=0,
        target_node_id="node-2", target_adapter=0, target_port=1,
    )
    assert link["link_id"] == "link-created"
    assert link["nodes"][0]["node_id"] == "node-1"
    provider.start_node("lab-1", "node-1")
    provider.stop_node("lab-1", "node-1")
    provider.delete_link("lab-1", "link-1")
    provider.delete_node("lab-1", "node-1")
    provider.delete_lab("lab-1")
    assert provider.capture_support()["supported"] is True
    assert provider.get_observed_topology("lab-1")["project_id"] == "lab-1"


def test_cml_resource_and_image_observations_remain_unknown_when_access_is_restricted():
    provider = CMLFixture()
    provider.restricted = {"/api/v0/system/compute_hosts", "/api/v0/licensing",
                           "/api/v0/node_definitions/iosv/image_definitions"}
    resources = provider.get_resource_availability()
    assert resources["computes"] == []
    assert resources["compute_observation"] == "RESTRICTED"
    assert resources["licensing_observation"] == "RESTRICTED"
    image = provider.get_template_image_availability("iosv")
    assert image["status"] == "UNKNOWN"
    assert image["available_images"] == []
    assert "HTTP 403" not in image.get("reason", "")


def test_private_provider_endpoint_policy_and_shared_http_request_hardening():
    assert validate_provider_endpoint("http://127.0.0.1:80") == "http://127.0.0.1:80"
    assert validate_provider_endpoint("https://192.168.1.20") == "https://192.168.1.20"
    for endpoint in ("https://example.com", "http://192.168.1.20",
                     "https://user:pass@192.168.1.20", "https://192.168.1.20/path"):
        with pytest.raises(ProviderHTTPError):
            validate_provider_endpoint(endpoint)

    class Response:
        status_code = 200

        def iter_content(self, chunk_size):
            assert chunk_size == 65536
            yield b'{"ok":true}'

        def close(self):
            self.closed = True

    class Session:
        def __init__(self):
            self.trust_env = True
            self.calls = []
            self.closed = False

        def request(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return Response()

        def close(self):
            self.closed = True

    sessions = []
    def factory():
        session = Session()
        sessions.append(session)
        return session

    http = ProviderHTTPSession("https://192.168.1.20", session_factory=factory)
    session = sessions[0]
    assert session.trust_env is False
    assert http.request("GET", "/api/v0/system_information") == {"ok": True}
    args, kwargs = session.calls[0]
    assert kwargs["verify"] is True and kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (3.05, 25.0)
    http.close()
    assert session.closed is True


def test_cml_session_refuses_calls_after_disconnect_and_rejects_unsafe_identifiers():
    provider = CMLFixture()
    provider.connect()
    provider.disconnect()
    with pytest.raises(CMLProviderError, match="not authenticated"):
        provider.health_check()
    with pytest.raises(CMLProviderError):
        provider._segment("../labs", "lab_id")
    with pytest.raises(CMLProviderError):
        provider.create_lab(" ")
