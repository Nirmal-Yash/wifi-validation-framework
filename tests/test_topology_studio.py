from __future__ import annotations
import sqlite3
import pytest
from dashboard.app import create_app
from lib.security import AuthManager
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
