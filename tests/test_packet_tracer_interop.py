from __future__ import annotations

from io import BytesIO
import hashlib
import sqlite3

import pktlib
import pytest
from pktlib._codec import encode as encode_native_packet

from dashboard.app import create_app
from lib.repositories import SQLiteDatabase
from lib.security import AuthManager
from lib.services.packet_tracer_interop import (
    PacketTracerInteropConflict,
    PacketTracerInteropError,
    PacketTracerInteropNotFound,
    PacketTracerInteropService,
)
from lib.services.topology_studio import TopologyStudioService


def _native_packet() -> bytes:
    network = pktlib.new(seed=7)
    router = network.router("R1", "2911", at=(120, 180))
    pc = network.pc("PC1", at=(420, 180), ip="192.0.2.2/24", gateway="192.0.2.1")
    router["g0/0"].address = "192.0.2.1/24"
    pc["fa0"].connect(router["g0/0"])
    return network.to_bytes()


@pytest.fixture
def interop_database(tmp_path):
    database = SQLiteDatabase(tmp_path / "packet-tracer.sqlite")
    database.initialize()
    now = "2026-11-23T00:00:00+00:00"
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
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-1", "project-1", "Lab", "gns3", 1, "ACTIVE", now, now),
        )
    return database


def _import(database, content=None, *, scope_type="PROJECT", scope_id=None):
    service = PacketTracerInteropService(database)
    return service.import_file(
        project_id="project-1",
        name="Packet Tracer test",
        filename="lab.pkt",
        content=content if content is not None else _native_packet(),
        scope_type=scope_type,
        scope_id=scope_id,
        actor="test-operator",
    )


def test_import_creates_canonical_draft_and_immutable_native_provenance(interop_database):
    original = _native_packet()
    result = _import(interop_database, original)
    assert result["profile"]["project_id"] == "project-1"
    assert result["profile"]["scope_type"] == "PROJECT"
    assert result["revision"]["status"] == "DRAFT"
    assert len(result["revision"]["content_sha256"]) == 64
    assert result["source"]["format"] == "CISCO_PACKET_TRACER_PKT"
    assert result["source"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert result["report"]["native_application_reopen_verified"] is False
    assert result["report"]["counts"]["nodes"] == 2
    assert result["report"]["counts"]["links"] == 1
    assert all(node["template_id"] == "" for node in result["revision"]["definition"]["nodes"])
    with interop_database.connection() as connection:
        row = connection.execute(
            "SELECT source_bytes,sha256,size_bytes FROM topology_native_sources WHERE source_id=?",
            (result["source"]["source_id"],),
        ).fetchone()
        assert bytes(row["source_bytes"]) == original
        assert row["sha256"] == hashlib.sha256(bytes(row["source_bytes"])).hexdigest()
        assert row["size_bytes"] == len(original)
        with pytest.raises(sqlite3.IntegrityError, match="provenance is immutable"):
            connection.execute(
                "UPDATE topology_native_sources SET filename='changed.pkt' WHERE source_id=?",
                (result["source"]["source_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            connection.execute(
                "DELETE FROM topology_native_sources WHERE source_id=?",
                (result["source"]["source_id"],),
            )


def test_import_creates_lab_scoped_topology_without_crossing_project_boundary(interop_database):
    result = _import(interop_database, scope_type="LAB", scope_id="lab-1")
    assert result["profile"]["project_id"] == "project-1"
    assert result["profile"]["scope_type"] == "LAB"
    assert result["profile"]["scope_id"] == "lab-1"
    with interop_database.connection() as connection:
        source = connection.execute(
            "SELECT project_id,profile_id,revision_id FROM topology_native_sources WHERE source_id=?",
            (result["source"]["source_id"],),
        ).fetchone()
        assert source["project_id"] == "project-1"
        assert source["profile_id"] == result["profile"]["profile_id"]
        assert source["revision_id"] == result["revision"]["revision_id"]


def test_noop_export_returns_exact_original_native_bytes(interop_database):
    original = _native_packet()
    result = _import(interop_database, original)
    exported = PacketTracerInteropService(interop_database).export_revision(
        profile_id=result["profile"]["profile_id"],
        revision_id=result["revision"]["revision_id"],
        source_id=result["source"]["source_id"],
    )
    assert exported.content == original
    assert exported.filename == "lab-netregress-export.pkt"
    assert exported.report["byte_identical_to_imported_source"] is True
    assert exported.report["read_back"]["codec_reopen"] is True
    assert exported.report["read_back"]["native_application_reopen_verified"] is False


def test_export_serializes_only_supported_native_name_and_coordinate_edits(interop_database):
    result = _import(interop_database)
    definition = result["revision"]["definition"]
    router = next(node for node in definition["nodes"] if node["node_type"] == "ROUTER")
    router["name"] = "Core-Router"
    router["x"] = min(10_000, router["x"] + 35)
    edited = TopologyStudioService(interop_database).create_revision(
        result["profile"]["profile_id"], definition=definition, actor="test-operator"
    )
    exported = PacketTracerInteropService(interop_database).export_revision(
        profile_id=result["profile"]["profile_id"],
        revision_id=edited["revision_id"],
        source_id=result["source"]["source_id"],
    )
    reopened = PacketTracerInteropService._load(exported.content)
    assert any(device.name == "Core-Router" for device in reopened.devices)
    assert exported.report["read_back"]["codec_reopen"] is True
    assert exported.report["supported_changes"] == ["node name", "node X/Y presentation coordinates"]


def test_export_refuses_unmapped_semantic_or_link_changes(interop_database):
    result = _import(interop_database)
    definition = result["revision"]["definition"]
    definition["nodes"][0]["interfaces"][0]["description"] = "cannot round-trip yet"
    edited = TopologyStudioService(interop_database).create_revision(
        result["profile"]["profile_id"], definition=definition, actor="test-operator"
    )
    with pytest.raises(PacketTracerInteropConflict, match="does not yet serialize"):
        PacketTracerInteropService(interop_database).export_revision(
            profile_id=result["profile"]["profile_id"],
            revision_id=edited["revision_id"],
            source_id=result["source"]["source_id"],
        )


def test_import_rejects_unsafe_names_malformed_files_foreign_scope_and_oversized_inflation(interop_database):
    service = PacketTracerInteropService(interop_database)
    with pytest.raises(PacketTracerInteropError, match="safe .pkt filename"):
        service.import_file(
            project_id="project-1", name="Invalid", filename="../escape.txt",
            content=_native_packet(), actor="operator",
        )
    with pytest.raises(PacketTracerInteropError, match="malformed"):
        service.import_file(
            project_id="project-1", name="Malformed", filename="bad.pkt",
            content=b"not a Packet Tracer file", actor="operator",
        )
    with pytest.raises(PacketTracerInteropNotFound, match="Lab not found"):
        _import(interop_database, scope_type="LAB", scope_id="foreign-lab")
    with pytest.raises(PacketTracerInteropError, match="must contain"):
        service.import_file(
            project_id="project-1", name="Empty", filename="empty.pkt",
            content=b"", actor="operator",
        )
    with pytest.raises(PacketTracerInteropError, match="must contain"):
        service.import_file(
            project_id="project-1", name="Oversized", filename="oversized.pkt",
            content=b"x" * (service.MAX_SOURCE_BYTES + 1), actor="operator",
        )

    compressed_bomb = encode_native_packet(b"x" * (service.MAX_EXPANDED_XML_BYTES + 1))
    assert len(compressed_bomb) < service.MAX_SOURCE_BYTES
    with pytest.raises(PacketTracerInteropError, match="safety limit"):
        service._load(compressed_bomb)

    entity_document = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<!DOCTYPE network [<!ENTITY payload "expanded">]>'
        b'<network>&payload;</network>'
    )
    entity_packet = encode_native_packet(entity_document)
    with pytest.raises(PacketTracerInteropError, match="DTD and entity declarations"):
        service._load(entity_packet)


def test_export_checks_native_source_integrity_and_revision_scope(interop_database):
    result = _import(interop_database)
    service = PacketTracerInteropService(interop_database)
    with interop_database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="provenance is immutable"):
            connection.execute(
                "UPDATE topology_native_sources SET source_bytes=? WHERE source_id=?",
                (b"bad", result["source"]["source_id"]),
            )
    with pytest.raises(PacketTracerInteropNotFound):
        service.export_revision(
            profile_id=result["profile"]["profile_id"],
            revision_id="another-profile-revision",
            source_id=result["source"]["source_id"],
        )


def test_packet_tracer_api_import_lists_source_and_downloads_export(interop_database):
    app = create_app(interop_database.path, auth_manager=AuthManager((), required=False))
    client = app.test_client()
    native = _native_packet()
    response = client.post(
        "/api/v1/topologies/import/packet-tracer",
        headers={"Idempotency-Key": "packet-tracer-import-0001"},
        data={
            "project_id": "project-1",
            "name": "API imported topology",
            "scope_type": "PROJECT",
            "file": (BytesIO(native), "api-lab.pkt"),
        },
    )
    assert response.status_code == 201
    data = response.get_json()["data"]
    profile_id = data["profile"]["profile_id"]
    retry = client.post(
        "/api/v1/topologies/import/packet-tracer",
        headers={"Idempotency-Key": "packet-tracer-import-0001"},
        data={
            "project_id": "project-1",
            "name": "API imported topology",
            "scope_type": "PROJECT",
            "file": (BytesIO(native), "api-lab.pkt"),
        },
    )
    assert retry.status_code == 201
    assert retry.get_json()["data"]["profile"]["profile_id"] == profile_id
    source_id = data["source"]["source_id"]
    revision_id = data["revision"]["revision_id"]

    sources = client.get(f"/api/v1/topologies/{profile_id}/native-sources")
    assert sources.status_code == 200
    assert sources.get_json()["data"]["items"][0]["source_id"] == source_id
    assert "source_bytes" not in sources.get_json()["data"]["items"][0]

    download = client.get(
        f"/api/v1/topologies/{profile_id}/native-sources/{source_id}/export?revision_id={revision_id}"
    )
    assert download.status_code == 200
    assert download.mimetype == "application/octet-stream"
    assert "api-lab-netregress-export.pkt" in download.headers["Content-Disposition"]
    assert download.data == native
    assert download.headers.get("X-NetRegress-Export-Report")



def test_packet_tracer_codec_joins_unified_native_registry_and_round_trips(interop_database):
    from lib.native_topology.packet_tracer import PacketTracerTopologyCodec
    from lib.native_topology.registry import default_registry

    source = _native_packet()
    codec = PacketTracerTopologyCodec()
    assert codec.detect(source, "native-lab.pkt") is True
    decoded = codec.decode(source, "native-lab.pkt")
    assert decoded.format_id == "CISCO_PACKET_TRACER_PKT"
    assert decoded.topology_definition["nodes"]
    assert decoded.presentation["layout_origin"] == "NATIVE"
    assert len(decoded.presentation["nodes"]) == len(decoded.topology_definition["nodes"])
    assert len(decoded.presentation["links"]) == len(decoded.topology_definition["links"])
    assert any("drawing objects" in warning for warning in decoded.warnings)
    assert "CISCO_PACKET_TRACER_PKT" in {
        item.format_id for item in default_registry().descriptors()
    }

    encoded = codec.encode(
        decoded.topology_definition,
        decoded.presentation,
        original_source=source,
        filename="native-lab.pkt",
    )
    assert encoded.content == source
    assert encoded.format_id == "CISCO_PACKET_TRACER_PKT"
    assert encoded.losses


def test_packet_tracer_generic_import_and_export_use_g02_provenance(interop_database):
    from lib.services.native_topology_interop import NativeTopologyInteropService

    source = _native_packet()
    service = NativeTopologyInteropService(interop_database)
    imported = service.import_file(
        project_id="project-1",
        name="Unified Packet Tracer",
        filename="unified.pkt",
        content=source,
        actor="test-operator",
    )
    assert imported["source"]["format_id"] == "CISCO_PACKET_TRACER_PKT"
    assert imported["source"]["sha256"] == hashlib.sha256(source).hexdigest()
    assert imported["presentation"]["source_artifact_id"] == imported["source"]["source_id"]
    assert imported["report"]["format_id"] == "CISCO_PACKET_TRACER_PKT"

    service.topology_studio.publish(
        imported["profile"]["profile_id"], imported["revision"]["revision_id"], actor="test-operator"
    )
    service.topology_presentation.publish(
        imported["presentation"]["presentation_id"],
        actor="test-operator",
        expected_profile_id=imported["profile"]["profile_id"],
    )
    exported = service.export_revision(
        profile_id=imported["profile"]["profile_id"],
        revision_id=imported["revision"]["revision_id"],
        presentation_id=imported["presentation"]["presentation_id"],
        source_id=imported["source"]["source_id"],
    )
    assert exported.content == source
    assert exported.report["originating_application_reopen"] == "NOT_VERIFIED"
    assert exported.report["losses"]
