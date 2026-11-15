from __future__ import annotations

import json
import pytest

from lib.repositories import SQLiteDatabase
from lib.services.credential_vault import CredentialVaultService
from lib.services.device_inventory import DeviceInventoryService
from lib.services.gns3_provider import GNS3Provider as RealGNS3Provider, GNS3ProviderError
from lib.services.resource_lock import ResourceLockManager
from lib.services.topology_apply import (
    TopologyApplyConflict, TopologyApplyError, TopologyApplyService,
)
from lib.services.topology_studio import TopologyStudioService


class MemorySecretStore:
    def __init__(self):
        self.values = {}

    def set(self, name, secret):
        self.values[name] = secret

    def get(self, name):
        return self.values.get(name)

    def delete(self, name):
        return self.values.pop(name, None) is not None


class FakeGNS3Provider:
    state = None

    @staticmethod
    def validate_endpoint(value, *, expected_host=None):
        return RealGNS3Provider.validate_endpoint(value, expected_host=expected_host)

    @staticmethod
    def _segment(value, name):
        return RealGNS3Provider._segment(value, name)

    def __init__(self, endpoint_url, username, password):
        assert endpoint_url.startswith("https://192.168.1.10:")
        assert username == "api-user"
        assert password == "transient-provider-secret"
        self.state = type(self).state

    def version(self):
        return {"version": "2.2.0"}

    def list_projects(self):
        return [{"project_id": "gns3-project", "name": "Wireless Lab", "status": "opened"}]

    def list_templates(self):
        return [
            {"template_id": "tpl-router", "name": "Router", "category": "router"},
            {"template_id": "tpl-switch", "name": "Switch", "category": "switch"},
        ]

    def list_nodes(self, project_id):
        return [dict(item) for item in self.state["nodes"]]

    def list_links(self, project_id):
        return [dict(item) for item in self.state["links"]]

    def create_node(self, project_id, template_id, *, name, x, y):
        node_id = "provider-node-" + str(len(self.state["nodes"]) + 1)
        ports = [
            {"adapter_number": 0, "port_number": port, "name": "Ethernet" + str(port)}
            for port in range(8)
        ]
        node = {
            "node_id": node_id, "name": name, "node_type": "qemu",
            "status": "stopped", "template_id": template_id, "x": x, "y": y,
            "ports": ports,
        }
        self.state["nodes"].append(node)
        return {"node_id": node_id, "name": name}

    def create_link(self, project_id, *, source_node_id, source_adapter, source_port,
                    target_node_id, target_adapter, target_port):
        link_id = "provider-link-" + str(len(self.state["links"]) + 1)
        self.state["links"].append({
            "link_id": link_id,
            "nodes": [
                {"node_id": source_node_id, "adapter_number": source_adapter, "port_number": source_port},
                {"node_id": target_node_id, "adapter_number": target_adapter, "port_number": target_port},
            ],
        })
        return {"link_id": link_id}

    def start_node(self, project_id, node_id):
        next(item for item in self.state["nodes"] if item["node_id"] == node_id)["status"] = "started"
        return {}

    def stop_node(self, project_id, node_id):
        next(item for item in self.state["nodes"] if item["node_id"] == node_id)["status"] = "stopped"
        return {}


def definition():
    return {
        "nodes": [
            {"id": "router-a", "name": "Router A", "node_type": "ROUTER", "template_id": "tpl-router", "x": 100, "y": 100},
            {"id": "switch-a", "name": "Switch A", "node_type": "SWITCH", "template_id": "tpl-switch", "x": 400, "y": 100},
        ],
        "links": [{
            "id": "link-a", "source_node_id": "router-a", "source_adapter": 0, "source_port": 0,
            "target_node_id": "switch-a", "target_adapter": 0, "target_port": 1,
        }],
    }


@pytest.fixture
def apply_stack(tmp_path, monkeypatch):
    import lib.services.topology_apply as apply_module

    database = SQLiteDatabase(tmp_path / "topology-apply.sqlite")
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
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-1", "project-1", "Wireless Lab", "gns3", 1, "ACTIVE", now, now),
        )
    inventory = DeviceInventoryService(database)
    device = inventory.create({
        "project_id": "project-1", "lab_id": "lab-1", "device_key": "gns3-controller",
        "name": "GNS3 Controller", "device_type": "SERVER", "host": "192.168.1.10",
        "port": 3080, "vendor": "GNS3", "model": "Controller",
    }, actor="owner")
    store = MemorySecretStore()
    vault = CredentialVaultService(database, store, secret_provider="test-os-vault")
    credential = vault.create(
        project_id="project-1", device_id=device["device_id"], label="GNS3 API",
        credential_type="API_TOKEN", username="api-user",
        secret="transient-provider-secret", actor="owner",
    )
    studio = TopologyStudioService(database)
    profile = studio.create_profile(
        project_id="project-1", name="Lab topology", scope_type="LAB",
        scope_id="lab-1", actor="owner",
    )
    revision = studio.create_revision(profile["profile_id"], definition=definition(), actor="owner")
    revision = studio.publish(profile["profile_id"], revision["revision_id"], actor="owner")
    FakeGNS3Provider.state = {"nodes": [], "links": []}
    monkeypatch.setattr(apply_module, "GNS3Provider", FakeGNS3Provider)
    service = TopologyApplyService(
        database, vault, studio,
        resource_lock_manager=ResourceLockManager(tmp_path / "locks"),
    )
    binding = service.bind(
        "lab-1", endpoint_url="https://192.168.1.10:3080",
        gns3_project_id="gns3-project", controller_device_id=device["device_id"],
        credential_id=credential["credential_id"], actor="owner",
    )
    return database, store, service, profile, revision, binding, FakeGNS3Provider.state


def test_provider_endpoint_is_private_tls_and_path_restricted():
    assert RealGNS3Provider.validate_endpoint("http://127.0.0.1:3080") == "http://127.0.0.1:3080"
    assert RealGNS3Provider.validate_endpoint("https://10.20.30.40:3080") == "https://10.20.30.40:3080"
    for value in (
        "http://example.com:3080",
        "https://example.com:3080",
        "https://user:pass@10.0.0.1:3080",
        "https://10.0.0.1:3080/v2",
        "https://10.0.0.1:3080/?target=metadata",
        "https://8.8.8.8:3080",
    ):
        with pytest.raises(GNS3ProviderError):
            RealGNS3Provider.validate_endpoint(value)


def test_binding_requires_lab_scoped_controller_and_api_token(apply_stack):
    _database, _store, service, _profile, _revision, binding, _state = apply_stack
    assert binding["lab_id"] == "lab-1"
    assert binding["credential_id"]
    assert "secret" not in json.dumps(binding).lower()
    with pytest.raises(TopologyApplyConflict, match="active API_TOKEN"):
        service.bind(
            "lab-1", endpoint_url="https://192.168.1.10:3080",
            gns3_project_id="gns3-project", controller_device_id=binding["controller_device_id"],
            credential_id="not-a-credential", actor="owner",
        )


def test_dry_run_is_read_only_and_apply_is_repeatable_and_reconciles(apply_stack):
    database, store, service, profile, revision, _binding, provider_state = apply_stack
    planned = service.plan(profile["profile_id"], revision["revision_id"], actor="owner")
    assert planned["plan"]["can_apply"] is True
    assert len(planned["plan"]["nodes_to_create"]) == 2
    assert planned["plan"]["links_pending_nodes"] == ["link-a"]
    assert provider_state["nodes"] == [] and provider_state["links"] == []
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM topology_provider_mappings").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM topology_apply_records").fetchone()[0] == 0

    result = service.apply(
        profile["profile_id"], revision["revision_id"],
        expected_sha256=revision["content_sha256"], confirmed=True, actor="owner",
    )
    assert result["status"] == "APPLIED"
    assert result["result"]["summary"]["created_nodes"] == 2
    assert result["result"]["summary"]["created_links"] == 1
    assert len(provider_state["nodes"]) == 2 and len(provider_state["links"]) == 1
    observed = service.reconcile(profile["profile_id"], revision["revision_id"], actor="owner")
    assert observed["status"] == "IN_SYNC"
    assert observed["missing_nodes"] == [] and observed["missing_links"] == []

    repeat_plan = service.plan(profile["profile_id"], revision["revision_id"], actor="owner")["plan"]
    assert repeat_plan["nodes_to_create"] == []
    assert repeat_plan["links_to_create"] == []
    repeated = service.apply(
        profile["profile_id"], revision["revision_id"],
        expected_sha256=revision["content_sha256"], confirmed=True, actor="owner",
    )
    assert repeated["status"] == "APPLIED"
    assert repeated["result"]["summary"]["created_nodes"] == 0
    assert len(provider_state["nodes"]) == 2 and len(provider_state["links"]) == 1
    assert "transient-provider-secret" not in json.dumps(service.list_applies("lab-1"))
    assert len(store.values) == 1


def test_port_conflict_blocks_apply_without_mutating_provider(apply_stack):
    _database, _store, service, profile, revision, _binding, state = apply_stack
    service.apply(
        profile["profile_id"], revision["revision_id"],
        expected_sha256=revision["content_sha256"], confirmed=True, actor="owner",
    )
    state["links"].clear()
    state["links"].append({
        "link_id": "unmanaged-link",
        "nodes": [
            {"node_id": "provider-node-1", "adapter_number": 0, "port_number": 0},
            {"node_id": "unmanaged-node", "adapter_number": 0, "port_number": 0},
        ],
    })
    before = json.dumps(state, sort_keys=True)
    plan = service.plan(profile["profile_id"], revision["revision_id"], actor="owner")["plan"]
    assert plan["can_apply"] is False
    assert any(item["resource_id"] == "link-a" for item in plan["conflicts"])
    with pytest.raises(TopologyApplyConflict, match="dry-run found provider conflicts"):
        service.apply(
            profile["profile_id"], revision["revision_id"],
            expected_sha256=revision["content_sha256"], confirmed=True, actor="owner",
        )
    assert json.dumps(state, sort_keys=True) == before


def test_provider_lifecycle_is_explicit_and_idempotent(apply_stack):
    _database, _store, service, profile, revision, _binding, state = apply_stack
    service.apply(
        profile["profile_id"], revision["revision_id"],
        expected_sha256=revision["content_sha256"], confirmed=True, actor="owner",
    )
    started = service.operate_node(profile["profile_id"], "router-a", action="START", actor="owner")
    assert started["status"] == "started"
    again = service.operate_node(profile["profile_id"], "router-a", action="START", actor="owner")
    assert again["already_in_requested_state"] is True
    stopped = service.operate_node(profile["profile_id"], "router-a", action="STOP", actor="owner")
    assert stopped["status"] == "stopped"
    assert state["nodes"][0]["status"] == "stopped"


def test_published_revision_hash_must_match_and_confirmation_is_mandatory(apply_stack):
    _database, _store, service, profile, revision, _binding, state = apply_stack
    with pytest.raises(TopologyApplyConflict, match="explicit confirmation"):
        service.apply(
            profile["profile_id"], revision["revision_id"],
            expected_sha256=revision["content_sha256"], confirmed=False, actor="owner",
        )
    with pytest.raises(TopologyApplyConflict, match="hash changed"):
        service.apply(
            profile["profile_id"], revision["revision_id"],
            expected_sha256="0" * 64, confirmed=True, actor="owner",
        )
    assert state["nodes"] == [] and state["links"] == []


def test_topology_provider_dashboard_routes_are_wired_and_idempotent(apply_stack, monkeypatch):
    from dashboard import api_v1 as api_module
    from dashboard.app import create_app
    from lib.security import AuthManager

    database, store, _service, profile, revision, binding, state = apply_stack

    class FakeAdapter:
        descriptor = type("Descriptor", (), {"family": type("Family", (), {"value": "test-os-vault"})()})()

        def create_secret_store(self):
            return store

    monkeypatch.setattr(api_module, "platform_adapter_for", lambda: FakeAdapter())
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()

    current_binding = client.get("/api/v1/labs/lab-1/provider-binding")
    assert current_binding.status_code == 200
    assert current_binding.get_json()["data"]["binding"]["binding_id"] == binding["binding_id"]

    rebound = client.put(
        "/api/v1/labs/lab-1/provider-binding",
        json={
            "endpoint_url": binding["endpoint_url"],
            "gns3_project_id": binding["gns3_project_id"],
            "controller_device_id": binding["controller_device_id"],
            "credential_id": binding["credential_id"],
        },
        headers={"Idempotency-Key": "topology-binding-put-01"},
    )
    assert rebound.status_code == 200
    assert rebound.get_json()["data"]["binding"]["binding_id"] == binding["binding_id"]

    catalog = client.get("/api/v1/labs/lab-1/provider-catalog")
    assert catalog.status_code == 200
    assert len(catalog.get_json()["data"]["catalog"]["templates"]) == 2

    planned = client.post(
        "/api/v1/topologies/" + profile["profile_id"] + "/plan",
        json={"revision_id": revision["revision_id"]},
        headers={"Idempotency-Key": "topology-dashboard-plan-01"},
    )
    assert planned.status_code == 200
    assert planned.get_json()["data"]["plan"]["can_apply"] is True
    assert state["nodes"] == [] and state["links"] == []

    payload = {
        "revision_id": revision["revision_id"],
        "expected_sha256": revision["content_sha256"],
        "confirmed": True,
    }
    headers = {"Idempotency-Key": "topology-dashboard-apply-01"}
    applied = client.post(
        "/api/v1/topologies/" + profile["profile_id"] + "/apply",
        json=payload,
        headers=headers,
    )
    assert applied.status_code == 200
    apply_id = applied.get_json()["data"]["apply_id"]
    assert applied.get_json()["data"]["status"] == "APPLIED"

    repeated = client.post(
        "/api/v1/topologies/" + profile["profile_id"] + "/apply",
        json=payload,
        headers=headers,
    )
    assert repeated.status_code == 200
    assert repeated.get_json()["data"]["apply_id"] == apply_id
    assert len(state["nodes"]) == 2 and len(state["links"]) == 1

    reconciled = client.get(
        "/api/v1/topologies/" + profile["profile_id"] + "/reconciliation"
        + "?revision_id=" + revision["revision_id"]
    )
    assert reconciled.status_code == 200
    assert reconciled.get_json()["data"]["status"] == "IN_SYNC"

    started = client.post(
        "/api/v1/topologies/" + profile["profile_id"] + "/nodes/router-a/start",
        json={}, headers={"Idempotency-Key": "topology-node-start-01"},
    )
    assert started.status_code == 200
    assert started.get_json()["data"]["status"] == "started"
    stopped = client.post(
        "/api/v1/topologies/" + profile["profile_id"] + "/nodes/router-a/stop",
        json={}, headers={"Idempotency-Key": "topology-node-stop-01"},
    )
    assert stopped.status_code == 200
    assert stopped.get_json()["data"]["status"] == "stopped"

    history = client.get("/api/v1/topologies/" + profile["profile_id"] + "/applies")
    assert history.status_code == 200
    assert [item["apply_id"] for item in history.get_json()["data"]["items"]] == [apply_id]
    assert "transient-provider-secret" not in json.dumps({
        "binding": current_binding.get_json(), "catalog": catalog.get_json(),
        "plan": planned.get_json(), "apply": applied.get_json(), "history": history.get_json(),
    })

    archived = client.delete(
        "/api/v1/labs/lab-1/provider-binding",
        headers={"Idempotency-Key": "topology-binding-archive-01"},
    )
    assert archived.status_code == 200
    assert archived.get_json()["data"]["binding"]["status"] == "ARCHIVED"
    assert client.get("/api/v1/labs/lab-1/provider-binding").get_json()["data"]["binding"] is None


def test_template_drift_blocks_apply_and_is_reported_by_reconciliation(apply_stack):
    _database, _store, service, profile, revision, _binding, state = apply_stack
    service.apply(
        profile["profile_id"], revision["revision_id"],
        expected_sha256=revision["content_sha256"], confirmed=True, actor="owner",
    )
    state["nodes"][0]["template_id"] = "unexpected-template"
    planned = service.plan(profile["profile_id"], revision["revision_id"], actor="owner")["plan"]
    assert planned["can_apply"] is False
    assert any("template" in item["reason"] for item in planned["conflicts"])
    observed = service.reconcile(profile["profile_id"], revision["revision_id"], actor="owner")
    assert observed["status"] == "DRIFTED"
    assert observed["mismatched_nodes"] == ["router-a"]


def test_provider_create_timeout_is_recorded_partial_and_recoverable(apply_stack, monkeypatch):
    import lib.services.topology_apply as apply_module

    _database, _store, service, profile, revision, _binding, state = apply_stack

    class TimeoutAfterCreate(FakeGNS3Provider):
        def create_node(self, project_id, template_id, *, name, x, y):
            super().create_node(project_id, template_id, name=name, x=x, y=y)
            raise TimeoutError("simulated controller response timeout")

    monkeypatch.setattr(apply_module, "GNS3Provider", TimeoutAfterCreate)
    with pytest.raises(TopologyApplyError, match="topology application stopped safely"):
        service.apply(
            profile["profile_id"], revision["revision_id"],
            expected_sha256=revision["content_sha256"], confirmed=True, actor="owner",
        )

    record = service.list_applies("lab-1")[0]
    assert record["status"] == "PARTIAL"
    assert record["result"]["operations"]["attempted_nodes"] == ["router-a"]
    assert record["result"]["operations"]["created_nodes"] == []
    assert len(record["observed_after"]["nodes"]) == 1

    monkeypatch.setattr(apply_module, "GNS3Provider", FakeGNS3Provider)
    recovered = service.plan(profile["profile_id"], revision["revision_id"], actor="owner")["plan"]
    assert [item["logical_node_id"] for item in recovered["adopt_nodes"]] == ["router-a"]
    assert [item["logical_node_id"] for item in recovered["nodes_to_create"]] == ["switch-a"]


def test_node_lifecycle_requires_verified_provider_state(apply_stack, monkeypatch):
    import lib.services.topology_apply as apply_module

    _database, _store, service, profile, revision, _binding, state = apply_stack
    service.apply(
        profile["profile_id"], revision["revision_id"],
        expected_sha256=revision["content_sha256"], confirmed=True, actor="owner",
    )

    class DoesNotStart(FakeGNS3Provider):
        def start_node(self, project_id, node_id):
            return {}

    monkeypatch.setattr(apply_module, "GNS3Provider", DoesNotStart)
    with pytest.raises(TopologyApplyError, match="did not reach the explicitly requested lifecycle state"):
        service.operate_node(profile["profile_id"], "router-a", action="START", actor="owner")
    assert state["nodes"][0]["status"] == "stopped"
