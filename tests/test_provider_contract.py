"""Contract, capability and safe provider-connection projection tests."""
import pytest

from lib.providers import (
    CapabilityRegistry, DEFAULT_CAPABILITIES, ProviderCapability,
    ProviderCapabilityError, ProviderConnectionRecord, ProviderContractError,
    ProviderDescriptor, ProviderNotRegisteredError, ProviderRegistry,
)


class CompleteProvider:
    def connect(self): return {"connected": True}
    def disconnect(self): return None
    def health_check(self): return {"status": "HEALTHY"}
    def get_capabilities(self): return []
    def version(self): return {"version": "test"}
    def list_projects(self): return []
    def create_lab(self, name, *, scene_width=1600, scene_height=900): return {"project_id": "p"}
    def delete_lab(self, project_id): return {"deleted": True}
    def list_templates(self): return []
    def list_nodes(self, project_id): return []
    def list_links(self, project_id): return []
    def create_node(self, project_id, template_id, *, name, x, y): return {"node_id": "n"}
    def delete_node(self, project_id, node_id): return {"deleted": True}
    def start_node(self, project_id, node_id): return None
    def stop_node(self, project_id, node_id): return None
    def get_node_state(self, project_id, node_id): return {"node_id": node_id}
    def create_link(self, project_id, **kwargs): return {"link_id": "l"}
    def delete_link(self, project_id, link_id): return {"deleted": True}
    def get_interfaces(self, project_id, node_id): return []
    def get_observed_topology(self, project_id): return {"nodes": [], "links": []}
    def capture_support(self): return {"supported": False}
    def get_resource_availability(self): return {"computes": []}
    def get_template_image_availability(self, template_id):
        return {"template_id": template_id, "status": "UNKNOWN", "missing_images": []}


class IncompleteProvider:
    def version(self): return {"version": "test"}


def registry_for(factory):
    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            provider_id="test", name="Test provider",
            description="A deterministic provider contract fixture.",
            capability_ids=("projects.read", "topology.nodes.create"),
        ),
        factory,
    )
    return registry


def test_provider_session_service_resolves_vault_secret_connects_and_always_disconnects():
    from lib.providers import ProviderSessionService

    events = []
    captured = {}

    class MemoryVault:
        def use_secret(self, credential_id, *, project_id, device_id, credential_type, actor, consumer):
            captured.update({
                "credential_id": credential_id, "project_id": project_id,
                "device_id": device_id, "credential_type": credential_type, "actor": actor,
            })
            return consumer({"username": "provider-user"}, "ephemeral-vault-secret")

    class TrackingProvider(CompleteProvider):
        def __init__(self, endpoint_url, username, password):
            captured.update({"endpoint_url": endpoint_url, "username": username})
            assert password == "ephemeral-vault-secret"

        def connect(self):
            events.append("connect")
            return {"connected": True}

        def disconnect(self):
            events.append("disconnect")

    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            provider_id="test", name="Test provider",
            description="A deterministic provider session fixture.",
            capability_ids=("projects.read",),
        ),
        TrackingProvider,
    )
    sessions = ProviderSessionService(MemoryVault(), registry)
    binding = {
        "provider_id": "test", "endpoint_url": "https://127.0.0.1:3080",
        "project_id": "project-1", "controller_device_id": "device-1",
        "credential_id": "vault-ref-1",
    }
    result = sessions.with_provider(
        binding, "operator",
        lambda provider: (events.append("callback"), provider.version())[1],
    )
    assert result == {"version": "test"}
    assert events == ["connect", "callback", "disconnect"]
    assert captured == {
        "credential_id": "vault-ref-1", "project_id": "project-1",
        "device_id": "device-1", "credential_type": "API_TOKEN", "actor": "operator",
        "endpoint_url": "https://127.0.0.1:3080", "username": "provider-user",
    }

    events.clear()
    with pytest.raises(RuntimeError, match="callback failed"):
        sessions.with_provider(
            binding, "operator",
            lambda provider: (_ for _ in ()).throw(RuntimeError("callback failed")),
        )
    assert events == ["connect", "disconnect"]


def test_capability_catalogue_has_stable_unique_ids_and_mutation_metadata():
    capability_ids = [item.capability_id for item in DEFAULT_CAPABILITIES]
    assert capability_ids == sorted(capability_ids)
    assert len(capability_ids) == len(set(capability_ids))
    catalogue = CapabilityRegistry()
    assert catalogue.get("projects.read").mutates_state is False
    assert catalogue.get("topology.nodes.create").mutates_state is True
    assert catalogue.get("topology.nodes.create").requires_confirmation is True
    assert all(not item.mutates_state or item.requires_confirmation for item in catalogue.list())


def test_capability_registry_rejects_duplicate_capability_ids():
    item = ProviderCapability("projects.read", "Projects", "Read projects")
    with pytest.raises(ValueError, match="duplicate"):
        CapabilityRegistry((item, item))


def test_gns3_reference_registry_declares_the_contract_capability_set():
    from lib.services.gns3_provider import GNS3Provider
    registry = ProviderRegistry.with_gns3()
    assert registry.descriptor("gns3").provider_id == "gns3"
    assert set(registry.capabilities_for("gns3")) == {item.capability_id for item in DEFAULT_CAPABILITIES}
    adapter = registry.create("gns3", "http://127.0.0.1:3080", "user", "transient")
    assert isinstance(adapter, GNS3Provider)
    assert callable(adapter.list_projects) and callable(adapter.create_link)


def test_registry_creates_conforming_adapter_and_lists_descriptor():
    registry = registry_for(CompleteProvider)
    assert isinstance(registry.create("test"), CompleteProvider)
    descriptor = registry.list_descriptors()[0]
    assert descriptor["provider_id"] == "test"
    assert {item["id"] for item in descriptor["capabilities"]} == {
        "projects.read", "topology.nodes.create",
    }


def test_registry_rejects_adapter_missing_required_contract_methods():
    with pytest.raises(ProviderContractError, match="list_projects"):
        registry_for(IncompleteProvider).create("test")


def test_registry_raises_typed_unknown_provider_and_unsupported_capability_errors():
    registry = registry_for(CompleteProvider)
    with pytest.raises(ProviderNotRegisteredError):
        registry.create("missing")
    with pytest.raises(ProviderCapabilityError, match="does not support"):
        registry.require_capability("test", "topology.nodes.stop")


def test_registration_rejects_capability_not_in_authoritative_catalogue():
    registry = ProviderRegistry()
    descriptor = ProviderDescriptor(
        provider_id="test", name="Test", description="Test",
        capability_ids=("made.up.capability",),
    )
    with pytest.raises(ProviderCapabilityError, match="unknown"):
        registry.register(descriptor, CompleteProvider)


def test_provider_connection_record_is_typed_and_never_contains_secret_material():
    binding = {
        "binding_id": "binding-1", "provider_id": "gns3",
        "project_id": "project-1", "lab_id": "lab-1",
        "endpoint_url": "https://192.168.1.10:3080",
        "gns3_project_id": "provider-project-1",
        "controller_device_id": "device-1", "credential_id": "vault-ref-1",
        "status": "ACTIVE", "created_at": "2026-11-22T00:00:00+00:00",
        "updated_at": "2026-11-22T00:00:00+00:00",
        "created_by": "owner", "updated_by": "owner",
        "password": "must-not-be-copied", "secret": "must-not-be-copied",
    }
    record = ProviderConnectionRecord.from_gns3_binding(binding)
    serialized = record.as_dict()
    assert serialized["provider_id"] == "gns3"
    assert serialized["credential_reference_id"] == "vault-ref-1"
    assert serialized["provider_workspace_id"] == "provider-project-1"
    assert "password" not in serialized and "secret" not in serialized
    assert "must-not-be-copied" not in repr(record)


def test_provider_connection_record_rejects_incomplete_binding():
    with pytest.raises(ValueError, match="missing required fields"):
        ProviderConnectionRecord.from_gns3_binding({"binding_id": "binding-1"})


def test_gns3_reference_adapter_exposes_complete_contract_without_live_network(monkeypatch):
    from lib.services.gns3_provider import GNS3Provider

    provider = GNS3Provider("http://127.0.0.1:3080", "test-user", "transient-secret")
    requests = []
    image_catalogue = ["router.qcow2"]

    def request(method, path, *, payload=None):
        requests.append((method, path, payload))
        if method == "GET" and path == "/v2/version":
            return {"version": "2.2.62", "local": True}
        if method == "GET" and path == "/v2/projects":
            return [{"project_id": "project-1", "name": "Lab", "status": "opened"}]
        if method == "POST" and path == "/v2/projects":
            return {"project_id": "project-new", "name": payload["name"], "status": "opened"}
        if method == "GET" and path == "/v2/templates":
            return [{
                "template_id": "template-1", "name": "Router",
                "template_type": "qemu", "compute_id": "compute-1",
                "hda_disk_image": "router.qcow2",
            }]
        if method == "GET" and path == "/v2/templates/template-1":
            return {
                "template_id": "template-1", "template_type": "qemu",
                "compute_id": "compute-1", "hda_disk_image": "router.qcow2",
            }
        if method == "GET" and path == "/v2/computes":
            return [{
                "compute_id": "compute-1", "name": "Local compute",
                "connected": True, "cpu_usage_percent": 12.5,
                "memory_usage_percent": 45.0, "host": "must-not-be-exposed",
                "last_error": "must-not-be-exposed",
            }]
        if method == "GET" and path == "/v2/computes/compute-1/qemu/images":
            return list(image_catalogue)
        if method == "POST" and path.endswith("/templates/template-1"):
            return {"node_id": "node-1", "name": payload["name"], "status": "stopped"}
        if method == "GET" and path.endswith("/nodes/node-1"):
            return {
                "node_id": "node-1", "status": "started",
                "ports": [{"adapter_number": 0, "port_number": 1, "name": "Ethernet 1"}],
            }
        if method == "GET" and path.endswith("/nodes"):
            return [{"node_id": "node-1", "status": "started", "ports": []}]
        if method == "GET" and path.endswith("/links"):
            return [{"link_id": "link-1", "nodes": []}]
        if method == "POST" and path.endswith("/links"):
            return {"link_id": "link-1"}
        return None

    monkeypatch.setattr(provider, "_request", request)

    connected = provider.connect()
    assert connected["connected"] is True
    assert connected["status"] == "HEALTHY"
    assert provider.health_check()["status"] == "HEALTHY"
    capability_ids = {item["id"] for item in provider.get_capabilities()}
    assert {
        "connection.health.read", "labs.create", "labs.delete",
        "topology.nodes.delete", "topology.links.delete",
        "topology.interfaces.read", "topology.observed.read",
        "packet_capture.supported", "resources.availability.read", "templates.images.read",
    } <= capability_ids

    assert provider.list_projects()[0]["project_id"] == "project-1"
    assert provider.list_templates()[0]["template_id"] == "template-1"
    resources = provider.get_resource_availability()
    assert resources["computes"][0]["cpu_usage_percent"] == 12.5
    assert resources["computes"][0]["memory_usage_percent"] == 45.0
    assert "host" not in resources["computes"][0] and "last_error" not in resources["computes"][0]
    image_check = provider.get_template_image_availability("template-1")
    assert image_check["status"] == "AVAILABLE"
    assert image_check["required_images"] == ["router.qcow2"]
    image_catalogue.clear()
    missing_image_check = provider.get_template_image_availability("template-1")
    assert missing_image_check["status"] == "MISSING"
    assert missing_image_check["missing_images"] == ["router.qcow2"]
    image_catalogue.append("router.qcow2")
    assert provider.create_lab("New Lab")["project_id"] == "project-new"
    provider.delete_lab("project-new")
    assert provider.create_node("project-1", "template-1", name="Router", x=10, y=20)["node_id"] == "node-1"
    assert provider.get_node_state("project-1", "node-1")["status"] == "started"
    assert provider.get_interfaces("project-1", "node-1")[0]["port_number"] == 1
    assert provider.list_nodes("project-1")[0]["node_id"] == "node-1"
    assert provider.list_links("project-1")[0]["link_id"] == "link-1"
    observed = provider.get_observed_topology("project-1")
    assert observed["nodes"][0]["node_id"] == "node-1"
    assert observed["links"][0]["link_id"] == "link-1"
    assert provider.create_link(
        "project-1", source_node_id="node-1", source_adapter=0, source_port=0,
        target_node_id="node-2", target_adapter=0, target_port=1,
    )["link_id"] == "link-1"
    provider.start_node("project-1", "node-1")
    provider.stop_node("project-1", "node-1")
    provider.delete_link("project-1", "link-1")
    provider.delete_node("project-1", "node-1")
    assert provider.capture_support()["supported"] is True
    provider.disconnect()
    assert provider._connected is False
    assert all("transient-secret" not in repr(item) for item in requests)
