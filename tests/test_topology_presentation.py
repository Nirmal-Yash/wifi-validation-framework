from __future__ import annotations

import json
import sqlite3

import pytest

from dashboard.app import create_app
from lib.repositories import SQLiteDatabase
from lib.security import AuthManager
from lib.services.topology_studio import TopologyStudioService
from lib.services.topology_metadata import MetadataValidationError, safe_relative_path
from lib.services.topology_presentation import (
    TopologyPresentationConflict,
    TopologyPresentationError,
    TopologyPresentationService,
)
from lib.services.topology_source_artifacts import (
    TopologySourceArtifactError,
    TopologySourceArtifactNotFound,
    TopologySourceArtifactService,
)


def _definition():
    return {
        "nodes": [
            {
                "id": "router-a", "name": "Router A", "node_type": "ROUTER",
                "template_id": "tpl-router", "x": 120, "y": 180,
                "interfaces": [{"name": "GigabitEthernet0/0", "adapter": 0, "port": 0}],
            },
            {
                "id": "switch-a", "name": "Switch A", "node_type": "SWITCH",
                "template_id": "tpl-switch", "x": 420, "y": 180,
                "interfaces": [{"name": "Ethernet1/1", "adapter": 0, "port": 1}],
            },
        ],
        "links": [{
            "id": "link-a", "source_node_id": "router-a",
            "source_adapter": 0, "source_port": 0, "source_interface_name": "GigabitEthernet0/0",
            "target_node_id": "switch-a", "target_adapter": 0,
            "target_port": 1, "target_interface_name": "Ethernet1/1",
        }],
    }


@pytest.fixture
def presentation_env(tmp_path):
    database = SQLiteDatabase(tmp_path / "presentation.sqlite")
    database.initialize()
    now = "2026-11-24T00:00:00+00:00"
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
            ("project-2", "org-1", "other", "Other", "ACTIVE", now, now),
        )
    topology = TopologyStudioService(database)
    profile = topology.create_profile(project_id="project-1", name="Native workspace", actor="owner")
    other_profile = topology.create_profile(project_id="project-2", name="Other workspace", actor="owner")
    revision = topology.create_revision(profile["profile_id"], definition=_definition(), actor="owner")
    other_revision = topology.create_revision(other_profile["profile_id"], definition=_definition(), actor="owner")
    return (
        database, topology, profile, revision, other_profile, other_revision,
        TopologyPresentationService(database), TopologySourceArtifactService(database),
    )


def _native_presentation(source_id: str):
    return {
        "schema_version": "1.0",
        "layout_origin": "NATIVE",
        "format_id": "GNS3_PROJECT",
        "format_version": "2.2.0",
        "source_artifact_id": source_id,
        "coordinate_space": {
            "unit": "px", "origin": "top_left",
            "x_axis": "right", "y_axis": "down",
            "scale": 1, "offset_x": 0, "offset_y": 0,
        },
        "canvas": {"width": 1440, "height": 900, "background": "#ffffff"},
        "viewport": {"x": 0, "y": 0, "width": 1440, "height": 900, "zoom": 1},
        "grid": {"enabled": True, "snap": False, "size": 20},
        "layers": [{"id": "network", "name": "Network", "visible": True, "locked": False, "z_index": 0, "native_id": "layer-1"}],
        "nodes": [
            {
                "node_id": "router-a", "native_id": "native-router-1",
                "x": 160, "y": 220, "width": 96, "height": 72,
                "rotation": 0, "icon_ref": "router-template",
                "icon_asset_path": "icons/router.svg", "template_ref": "router-template",
                "z_index": 3, "label": "Edge Router", "layer_id": "network",
                "ports": [{
                    "interface_name": "GigabitEthernet0/0", "adapter": 0, "port": 0,
                    "side": "E", "anchor_x": 1, "anchor_y": 0.5, "native_id": "port-1",
                }],
                "extensions": {"gns3": {"template_version": "1"}},
            },
        ],
        "links": [{
            "link_id": "link-a", "native_id": "native-link-1",
            "route_style": "orthogonal", "points": [{"x": 250, "y": 220}, {"x": 320, "y": 220}, {"x": 320, "y": 180}],
            "label": "Uplink", "z_index": 1,
            "extensions": {"gns3": {"link_style": "straight"}},
        }],
        "drawings": [{
            "id": "drawing-a", "native_id": "drawing-1", "kind": "TEXT",
            "x": 80, "y": 70, "text": "Core network", "layer_id": "network",
            "style": {"font_size": 14, "text_align": "start"},
        }],
        "extensions": {"gns3": {"project_property": {"retain": True}}},
    }


def test_native_presentation_is_hash_pinned_immutable_and_round_trippable(presentation_env):
    database, topology, profile, revision, _other_profile, _other_revision, service, sources = presentation_env
    asset = b'<svg xmlns="http://www.w3.org/2000/svg"><circle cx="5" cy="5" r="4"/></svg>'
    source = sources.record_source_artifact(
        profile["profile_id"], revision["revision_id"],
        source_bytes=b"native-gns3-project-fixture",
        format_id="GNS3_PROJECT", format_version="2.2.0",
        filename="lab.gns3", codec_name="gns3-json", codec_version="1.0",
        metadata={"parser": {"source": "test-fixture", "unknown_fields": 1}},
        assets=[{"relative_path": "icons/router.svg", "media_type": "image/svg+xml", "content_bytes": asset}],
        actor="owner",
    )
    payload = _native_presentation(source["source_id"])
    created = service.create_revision(revision["revision_id"], presentation=payload, actor="owner")

    assert created["status"] == "DRAFT"
    assert created["profile_id"] == profile["profile_id"]
    assert created["topology_revision_id"] == revision["revision_id"]
    assert created["topology_content_sha256"] == revision["content_sha256"]
    assert created["presentation"]["extensions"]["gns3"]["project_property"]["retain"] is True
    assert created["presentation"]["nodes"][0]["layer_id"] == "network"
    assert created["presentation_sha256"] == service.canonical_payload(payload, revision["definition"])[2]
    assert service.list_revisions(revision["revision_id"])[0]["presentation_id"] == created["presentation_id"]
    assert sources.get_source_artifact(source["source_id"], include_bytes=True)["source_bytes"] == b"native-gns3-project-fixture"
    assets = sources.list_assets(source["source_id"])
    assert len(assets) == 1
    assert sources.get_asset_bytes(source["source_id"], assets[0]["asset_id"]) == asset

    with pytest.raises(TopologyPresentationConflict, match="publish the pinned canonical topology"):
        service.publish(created["presentation_id"], actor="owner")

    topology.publish(profile["profile_id"], revision["revision_id"], actor="owner")
    published = service.publish(created["presentation_id"], actor="publisher", expected_profile_id=profile["profile_id"])
    assert published["status"] == "PUBLISHED"
    assert published["published_by"] == "publisher"

    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="revision content is immutable"):
            connection.execute(
                "UPDATE topology_presentation_revisions SET presentation_json='{}' WHERE presentation_id=?",
                (created["presentation_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="history cannot be deleted"):
            connection.execute(
                "DELETE FROM topology_presentation_revisions WHERE presentation_id=?",
                (created["presentation_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="provenance is immutable"):
            connection.execute(
                "UPDATE topology_source_artifacts SET filename='changed.gns3' WHERE source_id=?",
                (source["source_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="content is immutable"):
            connection.execute(
                "UPDATE topology_source_assets SET media_type='text/plain' WHERE source_id=?",
                (source["source_id"],),
            )


def test_presentation_rejects_unbound_native_and_malformed_extensions(presentation_env):
    _database, _topology, _profile, revision, _other_profile, _other_revision, service, _sources = presentation_env
    with pytest.raises(TopologyPresentationError, match="source_artifact_id"):
        service.normalize_presentation({
            "schema_version": "1.0", "layout_origin": "NATIVE",
            "format_id": "GNS3_PROJECT", "format_version": "2.2.0",
            "coordinate_space": {"unit": "px", "origin": "top_left"},
        }, revision["definition"])
    bad_extension = {
        "schema_version": "1.0", "layout_origin": "NETREGRESS",
        "extensions": {"gns3": {"password": "must-not-be-stored"}},
    }
    with pytest.raises(TopologyPresentationError, match="credential-like"):
        service.normalize_presentation(bad_extension, revision["definition"])
    bad_root = {"schema_version": "1.0", "layout_origin": "NETREGRESS", "unmodeled": {"value": 1}}
    with pytest.raises(TopologyPresentationError, match="supported fields"):
        service.normalize_presentation(bad_root, revision["definition"])
    bad_layer = {
        "schema_version": "1.0", "layout_origin": "NETREGRESS",
        "layers": [{"id": "network", "name": "Network"}],
        "nodes": [{"node_id": "router-a", "x": 10, "y": 10, "layer_id": "missing-layer"}],
    }
    with pytest.raises(TopologyPresentationError, match="unknown layer"):
        service.normalize_presentation(bad_layer, revision["definition"])
    bad_path = {
        "schema_version": "1.0", "layout_origin": "NETREGRESS",
        "nodes": [{"node_id": "router-a", "x": 10, "y": 10, "icon_asset_path": "../router.svg"}],
    }
    with pytest.raises(TopologyPresentationError, match="relative POSIX path"):
        service.normalize_presentation(bad_path, revision["definition"])


def test_source_artifacts_are_scope_bound_and_integrity_checked(presentation_env):
    database, _topology, profile, revision, other_profile, other_revision, _presentation, sources = presentation_env
    source = sources.record_source_artifact(
        profile["profile_id"], revision["revision_id"], source_bytes=b"native-source",
        format_id="CML_YAML", format_version="0.1", filename="lab.yaml",
        codec_name="cml-yaml", codec_version="1.0", metadata={"import": {"mode": "fixture"}},
        actor="owner",
    )
    with pytest.raises(TopologySourceArtifactNotFound):
        sources.record_source_artifact(
            profile["profile_id"], other_revision["revision_id"], source_bytes=b"foreign",
            format_id="CML_YAML", format_version="0.1", filename="foreign.yaml",
            codec_name="cml-yaml", codec_version="1.0", actor="owner",
        )
    with database.connection() as connection:
        connection.execute("DROP TRIGGER trg_topology_source_artifacts_immutable")
        connection.execute(
            "UPDATE topology_source_artifacts SET source_bytes=? WHERE source_id=?",
            (b"tampered-test", source["source_id"]),
        )
    with pytest.raises(TopologySourceArtifactError, match="SHA-256 integrity"):
        sources.get_source_artifact(source["source_id"], include_bytes=True)


def test_presentation_api_is_scoped_idempotent_and_permission_checked(presentation_env):
    database, topology, profile, revision, other_profile, _other_revision, _service, _sources = presentation_env
    app = create_app(database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()
    payload = {
        "presentation": {
            "schema_version": "1.0",
            "layout_origin": "NETREGRESS",
            "coordinate_space": {"unit": "px", "origin": "top_left"},
            "canvas": {"width": 1000, "height": 620},
            "viewport": {"x": 0, "y": 0, "width": 1000, "height": 620, "zoom": 1},
            "nodes": [{"node_id": "router-a", "x": 120, "y": 180, "width": 136, "height": 72}],
            "links": [{"link_id": "link-a", "route_style": "direct"}],
        }
    }
    created = client.post(
        f"/api/v1/topologies/{profile['profile_id']}/revisions/{revision['revision_id']}/presentation-revisions",
        headers={"Idempotency-Key": "presentation-create-0001"},
        json=payload,
    )
    assert created.status_code == 201
    presentation_id = created.get_json()["data"]["presentation_id"]

    repeated = client.post(
        f"/api/v1/topologies/{profile['profile_id']}/revisions/{revision['revision_id']}/presentation-revisions",
        headers={"Idempotency-Key": "presentation-create-0001"},
        json=payload,
    )
    assert repeated.status_code == 201
    assert repeated.get_json()["data"]["presentation_id"] == presentation_id

    listed = client.get(
        f"/api/v1/topologies/{profile['profile_id']}/revisions/{revision['revision_id']}/presentation-revisions"
    )
    assert listed.status_code == 200
    assert listed.get_json()["data"]["items"][0]["presentation_id"] == presentation_id

    foreign = client.post(
        f"/api/v1/topologies/{other_profile['profile_id']}/revisions/{revision['revision_id']}/presentation-revisions",
        headers={"Idempotency-Key": "presentation-create-foreign"},
        json=payload,
    )
    assert foreign.status_code == 404

    topology.publish(profile["profile_id"], revision["revision_id"], actor="owner")
    published = client.post(
        f"/api/v1/topologies/{profile['profile_id']}/presentation-revisions/{presentation_id}/publish",
        headers={"Idempotency-Key": "presentation-publish-0001"},
        json={},
    )
    assert published.status_code == 200
    assert published.get_json()["data"]["status"] == "PUBLISHED"


def test_source_artifact_path_validation_rejects_traversal_and_absolute_paths():
    for candidate in ("../secret", "a/../../secret", "/etc/passwd", r"icons\router.svg", "a//b", "a/./b"):
        with pytest.raises(MetadataValidationError):
            safe_relative_path(candidate)
    assert safe_relative_path("icons/router.svg") == "icons/router.svg"


def test_presentation_reads_verify_the_immutable_content_hash(presentation_env):
    database, _topology, _profile, revision, _other_profile, _other_revision, service, _sources = presentation_env
    payload = {
        "schema_version": "1.0",
        "layout_origin": "NETREGRESS",
        "nodes": [{"node_id": "router-a", "x": 10, "y": 20}],
    }
    created = service.create_revision(revision["revision_id"], presentation=payload, actor="owner")
    altered = dict(created["presentation"])
    altered["nodes"] = [dict(altered["nodes"][0], x=11)]
    changed_json = json.dumps(altered, sort_keys=True, separators=(",", ":"))
    with database.connection() as connection:
        connection.execute("DROP TRIGGER trg_topology_presentation_identity_immutable")
        connection.execute(
            "UPDATE topology_presentation_revisions SET presentation_json=? WHERE presentation_id=?",
            (changed_json, created["presentation_id"]),
        )
    with pytest.raises(TopologyPresentationConflict, match="SHA-256 integrity check"):
        service.get_revision(created["presentation_id"])
