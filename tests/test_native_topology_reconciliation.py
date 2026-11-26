from __future__ import annotations

import json
import sqlite3

import pytest

from dashboard.app import create_app
from lib.repositories import SQLiteDatabase
from lib.security import AuthManager
from lib.services.native_topology_interop import NativeTopologyInteropService
from lib.services.native_topology_reconciliation import (
    NativeTopologyReconciliationError,
    NativeTopologyReconciliationNotFound,
    NativeTopologyReconciliationService,
)


GNS3_SOURCE = json.dumps({
    "name": "Fixture GNS3 Lab",
    "project_id": "project-fixture-id",
    "type": "topology",
    "revision": 9,
    "version": "2.2.0",
    "scene_width": 1200,
    "scene_height": 800,
    "zoom": 1.25,
    "compute": {"name": "local", "extra_vendor_field": {"retain": True}},
    "topology": {
        "nodes": [
            {
                "node_id": "gns3-node-a", "name": "R1", "node_type": "dynamips",
                "compute_id": "local", "template_id": "c7200",
                "x": 100, "y": 120, "width": 70, "height": 45,
                "ports": [{"adapter_number": 0, "port_number": 0, "name": "FastEthernet0/0"}],
                "properties": {"custom": "keep"},
            },
            {
                "node_id": "gns3-node-b", "name": "R2", "node_type": "dynamips",
                "compute_id": "local", "template_id": "c7200",
                "x": 340, "y": 180, "width": 70, "height": 45,
            },
        ],
        "links": [
            {
                "link_id": "gns3-link-1",
                "nodes": [
                    {"node_id": "gns3-node-a", "adapter_number": 0, "port_number": 0},
                    {"node_id": "gns3-node-b", "adapter_number": 0, "port_number": 0},
                ],
                "label": "R1-R2",
            }
        ],
        "drawings": [{"drawing_id": "drawing-1", "svg": "<svg>retained</svg>"}],
    },
}, separators=(",", ":")).encode()


@pytest.fixture
def native_environment(tmp_path):
    database = SQLiteDatabase(tmp_path / "g12-native.sqlite")
    database.initialize()
    now = "2026-11-26T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO organizations(
                organization_id,slug,name,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?)""",
            ("org-g12", "g12-org", "G12 Org", "ACTIVE", now, now),
        )
        connection.execute(
            """INSERT INTO projects(
                project_id,organization_id,slug,name,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?)""",
            ("project-g12", "org-g12", "g12-project", "G12 Project", "ACTIVE", now, now),
        )
    interop = NativeTopologyInteropService(database)
    imported = interop.import_file(
        project_id="project-g12",
        name="G12 native topology",
        filename="g12-fixture.gns3",
        content=GNS3_SOURCE,
        actor="g12-test",
    )
    reconciliation = NativeTopologyReconciliationService(
        database,
        topology_studio=interop.topology_studio,
        topology_presentation=interop.topology_presentation,
        native_interop=interop,
    )
    return {
        "database": database,
        "interop": interop,
        "service": reconciliation,
        "profile": imported["profile"],
        "revision": imported["revision"],
        "presentation": imported["presentation"],
        "source": imported["source"],
    }


def _publish(environment):
    profile = environment["profile"]
    revision = environment["revision"]
    presentation = environment["presentation"]
    environment["interop"].topology_studio.publish(
        profile["profile_id"], revision["revision_id"], actor="g12-test",
    )
    environment["interop"].topology_presentation.publish(
        presentation["presentation_id"], actor="g12-test",
        expected_profile_id=profile["profile_id"],
    )


def _reconcile(environment):
    return environment["service"].reconcile(
        environment["profile"]["profile_id"],
        topology_revision_id=environment["revision"]["revision_id"],
        presentation_id=environment["presentation"]["presentation_id"],
        source_id=environment["source"]["source_id"],
        actor="g12-test",
    )


def test_reconciliation_verifies_native_source_and_codec_roundtrip_without_claiming_live_acceptance(native_environment):
    draft = _reconcile(native_environment)
    assert draft["status"] == "INCOMPLETE"
    assert draft["details"]["native_source"]["integrity"] == "VERIFIED"
    assert draft["details"]["native_export"]["status"] == "NOT_RUN"
    assert draft["details"]["external_acceptance"]["originating_vendor_application_reopen"] == "NOT_VERIFIED"

    _publish(native_environment)
    published = _reconcile(native_environment)
    assert published["status"] == "INCOMPLETE"  # no device/provider observation exists
    assert published["details"]["native_export"]["status"] == "VERIFIED"
    assert published["details"]["native_export"]["originating_application_reopen"] == "NOT_VERIFIED"
    assert published["details"]["native_source"]["sha256"] == native_environment["source"]["sha256"]
    assert published["details"]["native_source"]["integrity"] == "VERIFIED"
    assert published["details"]["topology"]["content_sha256"] == native_environment["revision"]["content_sha256"]
    assert any(item["code"] == "LIVE_OBSERVATION_NOT_AVAILABLE" for item in published["details"]["findings"])

    # A new service instance proves the persisted evidence can be read after restart.
    restarted = NativeTopologyReconciliationService(
        native_environment["database"],
        native_interop=native_environment["interop"],
    )
    recovered = restarted.get_reconciliation(
        native_environment["profile"]["profile_id"], published["reconciliation_id"],
    )
    assert recovered["reconciliation_sha256"] == published["reconciliation_sha256"]
    assert recovered["details"] == published["details"]
    assert restarted.list_reconciliations(native_environment["profile"]["profile_id"])[0]["reconciliation_id"] == published["reconciliation_id"]


def test_reconciliation_snapshots_and_operation_history_are_append_only(native_environment):
    _publish(native_environment)
    result = _reconcile(native_environment)
    db = native_environment["database"]
    with pytest.raises(sqlite3.IntegrityError, match="evidence is immutable"):
        with db.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE native_topology_reconciliations SET status='CLEAN' WHERE reconciliation_id=?",
                (result["reconciliation_id"],),
            )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        with db.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM native_topology_reconciliations WHERE reconciliation_id=?",
                (result["reconciliation_id"],),
            )

    operation = native_environment["service"].record_operation(
        "project-g12", "CONVERSION", actor="g12-test",
        details={
            "source": {"filename": "source.gns3", "sha256": "a" * 64},
            "output": {"filename": "target.unl", "sha256": "b" * 64},
            "losses": [{"category": "CONFIGURATION", "severity": "NOT_TRANSLATED"}],
        },
    )
    assert operation["operation_type"] == "CONVERSION"
    history = native_environment["service"].list_operations(native_environment["profile"]["profile_id"])
    assert any(item["resource_id"] == operation["operation_id"] for item in history)
    assert any(item["resource_type"] == "TOPOLOGY_SOURCE_ARTIFACT" for item in history)

    with pytest.raises(NativeTopologyReconciliationError, match="prohibited"):
        native_environment["service"].record_operation(
            "project-g12", "EXPORT", actor="g12-test", profile_id=native_environment["profile"]["profile_id"],
            details={"source_bytes": "never persist source file bytes"},
        )


def test_native_reconciliation_api_is_idempotent_and_exposes_history(native_environment):
    _publish(native_environment)
    client = create_app(
        native_environment["database"].path,
        auth_manager=AuthManager((), required=False),
    ).test_client()
    profile_id = native_environment["profile"]["profile_id"]
    payload = {
        "topology_revision_id": native_environment["revision"]["revision_id"],
        "presentation_id": native_environment["presentation"]["presentation_id"],
        "source_id": native_environment["source"]["source_id"],
    }
    headers = {"Idempotency-Key": "g12-reconciliation-request-0001"}
    first = client.post(
        f"/api/v1/topologies/{profile_id}/reconciliations",
        headers=headers, json=payload,
    )
    assert first.status_code == 201, first.get_json()
    second = client.post(
        f"/api/v1/topologies/{profile_id}/reconciliations",
        headers=headers, json=payload,
    )
    assert second.status_code == 201, second.get_json()
    assert first.get_json()["data"]["reconciliation_id"] == second.get_json()["data"]["reconciliation_id"]

    listed = client.get(f"/api/v1/topologies/{profile_id}/reconciliations")
    assert listed.status_code == 200
    assert listed.get_json()["data"]["items"][0]["reconciliation_id"] == first.get_json()["data"]["reconciliation_id"]
    fetched = client.get(
        f"/api/v1/topologies/{profile_id}/reconciliations/{first.get_json()['data']['reconciliation_id']}"
    )
    assert fetched.status_code == 200
    assert fetched.get_json()["data"]["reconciliation_sha256"] == first.get_json()["data"]["reconciliation_sha256"]
    operations = client.get(f"/api/v1/topologies/{profile_id}/native-operations")
    assert operations.status_code == 200
    assert any(item["resource_type"] == "TOPOLOGY_SOURCE_ARTIFACT" for item in operations.get_json()["data"]["items"])


def test_reconciliation_rejects_a_source_from_another_profile(native_environment):
    other = native_environment["interop"].import_file(
        project_id="project-g12", name="Second topology",
        filename="second.gns3", content=GNS3_SOURCE, actor="g12-test",
    )
    with pytest.raises(NativeTopologyReconciliationNotFound, match="source artifact was not found in this profile"):
        native_environment["service"].reconcile(
            native_environment["profile"]["profile_id"],
            topology_revision_id=native_environment["revision"]["revision_id"],
            presentation_id=native_environment["presentation"]["presentation_id"],
            source_id=other["source"]["source_id"],
            actor="g12-test",
        )


def test_partial_topology_apply_is_reported_as_reconciliation_required(tmp_path):
    database = SQLiteDatabase(tmp_path / "g12-partial.sqlite")
    database.initialize()
    now = "2026-11-26T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO organizations(
                organization_id,slug,name,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?)""",
            ("org-partial", "partial-org", "Partial Org", "ACTIVE", now, now),
        )
        connection.execute(
            """INSERT INTO projects(
                project_id,organization_id,slug,name,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?)""",
            ("project-partial", "org-partial", "partial-project", "Partial Project", "ACTIVE", now, now),
        )
        connection.execute(
            """INSERT INTO labs(
                lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            ("lab-partial", "project-partial", "Partial Lab", "gns3", "2.2.0", "ACTIVE", now, now),
        )
    interop = NativeTopologyInteropService(database)
    imported = interop.import_file(
        project_id="project-partial", name="Partial lab topology",
        filename="partial.gns3", content=GNS3_SOURCE,
        scope_type="LAB", scope_id="lab-partial", actor="g12-test",
    )
    interop.topology_studio.publish(
        imported["profile"]["profile_id"], imported["revision"]["revision_id"], actor="g12-test",
    )
    interop.topology_presentation.publish(
        imported["presentation"]["presentation_id"], actor="g12-test",
        expected_profile_id=imported["profile"]["profile_id"],
    )
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO topology_apply_records(
                apply_id,project_id,lab_id,profile_id,revision_id,content_sha256,status,
                plan_json,observed_before_json,observed_after_json,result_json,
                created_at,started_at,completed_at,created_by
            ) VALUES(?,?,?,?,?,?,'PARTIAL','{}','{}','{}',?,?,?,?,'g12-test')""",
            (
                "tpa-partial-g12", "project-partial", "lab-partial",
                imported["profile"]["profile_id"], imported["revision"]["revision_id"],
                imported["revision"]["content_sha256"],
                json.dumps({"summary": {"created_nodes": 1, "uncertain_operations": 1}}),
                now, now, now,
            ),
        )
    service = NativeTopologyReconciliationService(database, native_interop=interop)
    result = service.reconcile(
        imported["profile"]["profile_id"],
        topology_revision_id=imported["revision"]["revision_id"],
        presentation_id=imported["presentation"]["presentation_id"],
        source_id=imported["source"]["source_id"],
        actor="g12-test",
    )
    assert result["status"] == "RECONCILIATION_REQUIRED"
    uncertain = result["details"]["operations"]["uncertain"]
    assert len(uncertain) == 1
    assert uncertain[0]["system"] == "TOPOLOGY_APPLY"
    assert uncertain[0]["result_summary"]["created_nodes"] == 1
    assert uncertain[0]["partial_changes_possible"] is True

