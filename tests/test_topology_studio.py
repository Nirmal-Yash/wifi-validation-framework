from __future__ import annotations
import sqlite3
import pytest
from dashboard.app import create_app
from lib.security import AuthManager, Role, UserRecord
from lib.repositories import SQLiteDatabase
from lib.services.topology_studio import TopologyStudioError, TopologyStudioNotFound, TopologyStudioService

@pytest.fixture
def topology(tmp_path):
    database=SQLiteDatabase(tmp_path/"topology.sqlite")
    database.initialize()
    now="2026-11-15T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute("INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",("org-1","org","Organization","ACTIVE",now,now))
        connection.execute("INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",("project-1","org-1","project","Project","ACTIVE",now,now))
        connection.execute("INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",("project-2","org-1","other","Other","ACTIVE",now,now))
        connection.execute("INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",("lab-1","project-1","Lab","gns3",1,"ACTIVE",now,now))
        connection.execute("INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",("lab-2","project-2","Other Lab","gns3",1,"ACTIVE",now,now))
    return database,TopologyStudioService(database)

def definition():
    return {"nodes":[
        {"id":"router-a","name":"Router A","node_type":"ROUTER","template_id":"tpl-router","x":120,"y":180},
        {"id":"switch-a","name":"Switch A","node_type":"SWITCH","template_id":"tpl-switch","x":420,"y":180}],
        "links":[{"id":"link-a","source_node_id":"router-a","source_adapter":0,"source_port":0,
        "target_node_id":"switch-a","target_adapter":0,"target_port":1}]}

def test_canonical_topology_is_order_independent_and_hashed():
    first=definition();second={"nodes":list(reversed(first["nodes"])),"links":list(reversed(first["links"]))}
    assert TopologyStudioService.canonical_payload(first)[2]==TopologyStudioService.canonical_payload(second)[2]

@pytest.mark.parametrize("mutator,match",[
    (lambda d:d["nodes"].append(dict(d["nodes"][0])),"duplicated"),
    (lambda d:d["links"][0].update(target_node_id="missing"),"unknown logical node"),
    (lambda d:d["links"][0].update(target_node_id="router-a"),"itself"),
    (lambda d: (
        d["nodes"].append({"id": "client-a", "name": "Client A", "node_type": "CLIENT", "template_id": "tpl-client", "x": 700, "y": 180}),
        d["links"].append({"id": "link-b", "source_node_id": "router-a", "source_adapter": 0, "source_port": 0, "target_node_id": "client-a", "target_adapter": 0, "target_port": 0}),
    ), "occupied"),
    (lambda d:d["nodes"][0].update(properties={"api_token":"never"}),"credential-like"),
    (lambda d:d["nodes"][0].update(template_id="../unsafe"),"unsupported characters"),
])
def test_topology_validation_rejects_unsafe_or_ambiguous_definitions(mutator,match):
    value=definition();mutator(value)
    with pytest.raises(TopologyStudioError,match=match):TopologyStudioService.normalize_definition(value)

def test_profiles_are_project_lab_scoped_and_revisions_immutable(topology):
    database,service=topology
    project=service.create_profile(project_id="project-1",name="Project fabric",actor="owner")
    lab=service.create_profile(project_id="project-1",name="Lab fabric",scope_type="LAB",scope_id="lab-1",actor="owner")
    assert project["scope_id"]=="project-1" and project["lab_id"] is None
    assert lab["scope_id"]=="lab-1" and lab["lab_id"]=="lab-1"
    with pytest.raises(TopologyStudioNotFound):
        service.create_profile(project_id="project-1",name="Foreign",scope_type="LAB",scope_id="lab-2",actor="owner")
    revision=service.create_revision(lab["profile_id"],definition=definition(),actor="owner")
    assert revision["status"]=="DRAFT" and len(revision["content_sha256"])==64
    assert service.publish(lab["profile_id"],revision["revision_id"],actor="owner")["status"]=="PUBLISHED"
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError,match="revision content is immutable"):
            connection.execute("UPDATE topology_revisions SET definition_json='{}' WHERE revision_id=?",(revision["revision_id"],))
        with pytest.raises(sqlite3.IntegrityError,match="history cannot be deleted"):
            connection.execute("DELETE FROM topology_revisions WHERE revision_id=?",(revision["revision_id"],))
    assert len(service.list_revisions(lab["profile_id"]))==1



def test_topology_profile_revision_api_uses_standard_envelopes_and_idempotency(topology):
    database, _service = topology
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()

    created = client.post(
        "/api/v1/topologies",
        headers={"Idempotency-Key": "topology-profile-create-001"},
        json={"project_id": "project-1", "name": "API topology", "scope_type": "PROJECT"},
    )
    assert created.status_code == 201
    profile = created.get_json()["data"]
    assert profile["project_id"] == "project-1"

    revision = client.post(
        f"/api/v1/topologies/{profile['profile_id']}/revisions",
        headers={"Idempotency-Key": "topology-revision-create-001"},
        json={"definition": definition()},
    )
    assert revision.status_code == 201
    revision_data = revision.get_json()["data"]
    assert revision_data["status"] == "DRAFT"

    published = client.post(
        f"/api/v1/topologies/{profile['profile_id']}/publish",
        headers={"Idempotency-Key": "topology-revision-publish-001"},
        json={"revision_id": revision_data["revision_id"]},
    )
    assert published.status_code == 200
    assert published.get_json()["data"]["status"] == "PUBLISHED"

    listed = client.get("/api/v1/topologies?project_id=project-1")
    assert listed.status_code == 200
    assert [item["profile_id"] for item in listed.get_json()["data"]["items"]] == [profile["profile_id"]]



def test_topology_validation_api_returns_canonical_hash_without_persisting_revision(topology):
    database, service = topology
    profile = service.create_profile(
        project_id="project-1", name="Validation target", actor="owner",
    )
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()
    with database.connection() as connection:
        before = connection.execute(
            "SELECT COUNT(*) FROM topology_revisions WHERE profile_id=?",
            (profile["profile_id"],),
        ).fetchone()[0]

    response = client.post(
        "/api/v1/topologies/validate",
        json={
            "project_id": "project-1",
            "profile_id": profile["profile_id"],
            "definition": definition(),
        },
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["valid"] is True
    assert data["node_count"] == 2
    assert data["link_count"] == 1
    assert data["content_sha256"] == service.canonical_payload(definition())[2]
    with database.connection() as connection:
        after = connection.execute(
            "SELECT COUNT(*) FROM topology_revisions WHERE profile_id=?",
            (profile["profile_id"],),
        ).fetchone()[0]
    assert after == before


def test_topology_validation_api_returns_actionable_errors_for_port_conflicts(topology):
    database, _service = topology
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()
    invalid = definition()
    invalid["links"].append({
        "id": "link-b",
        "source_node_id": "router-a",
        "source_adapter": 0,
        "source_port": 0,
        "target_node_id": "switch-a",
        "target_adapter": 0,
        "target_port": 7,
    })
    response = client.post(
        "/api/v1/topologies/validate",
        json={"project_id": "project-1", "definition": invalid},
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_TOPOLOGY"
    assert "occupied" in response.get_json()["error"]["message"]
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM topology_revisions").fetchone()[0] == 0


def test_topology_validation_api_rejects_cross_project_profile_and_missing_scope(topology):
    database, service = topology
    profile = service.create_profile(project_id="project-2", name="Other Project", actor="owner")
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()
    missing = client.post("/api/v1/topologies/validate", json={"definition": definition()})
    assert missing.status_code == 400
    cross_scope = client.post(
        "/api/v1/topologies/validate",
        json={"project_id": "project-1", "profile_id": profile["profile_id"], "definition": definition()},
    )
    assert cross_scope.status_code == 404


def test_topology_validation_api_requires_topology_manage_permission(topology):
    database, _service = topology
    password = "correct-horse-battery-staple-2026"
    manager = AuthManager(
        (UserRecord("viewer", AuthManager.password_hash(password), Role.VIEWER, ("project-1",)),),
        required=True,
    )
    app = create_app(database.path, auth_manager=manager)
    app.config.update(TESTING=True)
    client = app.test_client()
    login = client.post("/api/v1/auth/login", json={"username": "viewer", "password": password})
    assert login.status_code == 200
    csrf = login.get_json()["data"]["csrf_token"]
    response = client.post(
        "/api/v1/topologies/validate",
        headers={"X-CSRF-Token": csrf},
        json={"project_id": "project-1", "definition": definition()},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "FORBIDDEN"


def test_structured_network_intent_and_interface_metadata_are_canonical(topology):
    _database, service = topology
    value = definition()
    value["nodes"][0].update({
        "template_id": "",
        "vendor": "Cisco",
        "operating_system": "IOSv",
        "image": "iosv-universalk9",
        "cpu_cores": 2,
        "memory_mb": 4096,
        "management_address": "192.0.2.1/24",
        "default_gateway": "192.0.2.254",
        "vlan_id": 10,
        "configuration_profile_id": "cfg-profile-1",
        "credential_ref_id": "cred_opaque_1",
        "interfaces": [{
            "name": "GigabitEthernet0/0", "adapter": 0, "port": 0,
            "mode": "ROUTED", "ip_address": "192.0.2.1/24", "description": "Management uplink",
        }],
    })
    value["nodes"][1]["interfaces"] = [{
        "name": "Ethernet0/1", "adapter": 0, "port": 1, "mode": "ACCESS", "vlan_id": 10,
    }]
    value["links"][0].update({
        "source_interface_name": "GigabitEthernet0/0",
        "target_interface_name": "Ethernet0/1",
        "link_type": "ETHERNET",
        "network_segment_id": "segment-mgmt",
        "vlan_id": 10,
    })

    normalized = service.normalize_definition(value)
    router = next(node for node in normalized["nodes"] if node["id"] == "router-a")
    link = normalized["links"][0]
    assert router["template_id"] == ""
    assert router["vendor"] == "Cisco"
    assert router["operating_system"] == "IOSv"
    assert router["cpu_cores"] == 2 and router["memory_mb"] == 4096
    assert router["management_address"] == "192.0.2.1/24"
    assert router["default_gateway"] == "192.0.2.254"
    assert router["credential_ref_id"] == "cred_opaque_1"
    assert router["interfaces"][0]["name"] == "GigabitEthernet0/0"
    assert link["source_interface_name"] == "GigabitEthernet0/0"
    assert link["target_interface_name"] == "Ethernet0/1"
    assert link["network_segment_id"] == "segment-mgmt" and link["vlan_id"] == 10
    canonical, _encoded, digest = service.canonical_payload(value)
    assert digest == service.canonical_payload(canonical)[2]


@pytest.mark.parametrize("mutator,match", [
    (lambda d: d["nodes"][0].update(cpu_cores=True), "cpu_cores must be an integer"),
    (lambda d: d["nodes"][0].update(memory_mb=64), "memory_mb must be an integer"),
    (lambda d: d["nodes"][0].update(management_address="999.1.1.1/24"), "valid IP address"),
    (lambda d: d["nodes"][0].update(vlan_id=4095), "vlan_id must be an integer"),
    (lambda d: d["nodes"][0].update(interfaces=[
        {"name": "eth0", "adapter": 0, "port": 0},
        {"name": "eth1", "adapter": 0, "port": 0},
    ]), "reuses an adapter/port"),
    (lambda d: d["nodes"][0].update(interfaces=[
        {"name": "eth0", "adapter": 0, "port": 0},
    ]), "source_interface_name does not exist"),
])
def test_structured_topology_metadata_rejects_invalid_resources(mutator, match):
    value = definition()
    if match.startswith("source_interface"):
        value["links"][0]["source_interface_name"] = "eth9"
    mutator(value)
    with pytest.raises(TopologyStudioError, match=match):
        TopologyStudioService.normalize_definition(value)


def test_logical_nodes_can_be_saved_before_provider_template_mapping(topology):
    _database, service = topology
    profile = service.create_profile(project_id="project-1", name="Provider-independent design", actor="owner")
    value = definition()
    value["nodes"][0]["template_id"] = ""
    revision = service.create_revision(profile["profile_id"], definition=value, actor="owner")
    assert revision["status"] == "DRAFT"
    assert next(node for node in revision["definition"]["nodes"] if node["id"] == "router-a")["template_id"] == ""




def _seed_foreign_topology_references(database):
    now = "2026-11-22T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO managed_credentials(
               credential_id,project_id,device_id,label,credential_type,username,secret_provider,
               secret_reference,status,verification_status,last_verified_at,verification_summary,
               rotated_at,created_at,updated_at,created_by,updated_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("cred-project-2", "project-2", "device-project-2", "Other Project API",
             "API_TOKEN", "api-user", "test-os-vault", "vault://project-2/credential",
             "ACTIVE", "NOT_VERIFIED", None, None, None, now, now, "owner", "owner"),
        )
        connection.execute(
            """INSERT INTO configuration_schemas(
               schema_record_id,project_id,schema_id,version,name,definition_json,status,created_at,created_by
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("schema-project-2", "project-2", "generic.test.v1", 1, "Other Project",
             "{}", "ACTIVE", now, "owner"),
        )
        connection.execute(
            """INSERT INTO configuration_profiles(
               profile_id,project_id,name,description,scope_type,scope_id,schema_record_id,status,
               created_at,updated_at,created_by,updated_by
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("config-project-2", "project-2", "Other Project Config", "", "PROJECT",
             "project-2", "schema-project-2", "PUBLISHED", now, now, "owner", "owner"),
        )

def test_topology_reference_ids_are_project_scoped_and_permission_checked(topology):
    database, _service = topology
    _seed_foreign_topology_references(database)
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()

    credential_response = client.post(
        "/api/v1/topologies/validate",
        json={
            "project_id": "project-1",
            "definition": {
                **definition(),
                "nodes": [
                    {**definition()["nodes"][0], "credential_ref_id": "cred-project-2"},
                    definition()["nodes"][1],
                ],
            },
        },
    )
    assert credential_response.status_code == 404
    assert credential_response.get_json()["error"]["code"] == "NOT_FOUND"

    configuration_response = client.post(
        "/api/v1/topologies/validate",
        json={
            "project_id": "project-1",
            "definition": {
                **definition(),
                "nodes": [
                    {**definition()["nodes"][0], "configuration_profile_id": "config-project-2"},
                    definition()["nodes"][1],
                ],
            },
        },
    )
    assert configuration_response.status_code == 404
    assert configuration_response.get_json()["error"]["code"] == "NOT_FOUND"


def test_immutable_revision_creation_rechecks_topology_reference_scope(topology):
    database, _service = topology
    _seed_foreign_topology_references(database)
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()
    profile = client.post(
        "/api/v1/topologies",
        json={"project_id": "project-1", "name": "Reference scope", "scope_type": "PROJECT"},
    )
    assert profile.status_code == 201
    profile_id = profile.get_json()["data"]["profile_id"]

    rejected = client.post(
        f"/api/v1/topologies/{profile_id}/revisions",
        json={
            "definition": {
                **definition(),
                "nodes": [
                    {**definition()["nodes"][0], "credential_ref_id": "cred-project-2"},
                    definition()["nodes"][1],
                ],
            },
        },
    )
    assert rejected.status_code == 404
    assert rejected.get_json()["error"]["code"] == "NOT_FOUND"
    with database.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM topology_revisions WHERE profile_id=?",
            (profile_id,),
        ).fetchone()[0] == 0


def test_legacy_links_without_optional_interface_metadata_remain_canonical(topology):
    _database, service = topology
    normalized, _encoded, digest = service.canonical_payload(definition())
    assert normalized["links"] == definition()["links"]
    assert len(digest) == 64
