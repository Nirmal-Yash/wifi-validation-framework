from __future__ import annotations

import json
from pathlib import Path

from lib.domain import (
    Criticality,
    EvidenceState,
    Metric,
    Run,
    Sample,
    Severity,
    TestResult,
    TestResultStatus,
)
from lib.repositories import (
    SQLiteDatabase,
    SQLiteRunRepository,
    SQLiteAttemptRepository,
    SQLiteEventRepository,
    SQLiteTestResultRepository,
)
from lib.services import ArtifactService, RunService
from dashboard.app import create_app


TEST_ID = "wifi.latency.threshold"


def make_service(db):
    return RunService(
        SQLiteRunRepository(db),
        SQLiteAttemptRepository(db),
        SQLiteEventRepository(db),
        SQLiteTestResultRepository(db),
    )


def create_run(service, firmware):
    run, attempt = service.create_run(
        firmware_version=firmware,
        lab_id="lab-1",
        validation_profile="Performance",
        selected_tests=[TEST_ID],
        test_definition_versions={TEST_ID: "1.0"},
        resolved_config={
            "regression": {"thresholds": {TEST_ID: {"latency": 10}}},
        },
        repository_commit="test-commit",
    )
    return run, attempt


def record(service, run, attempt, status, value):
    return service.record_test_result(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        test_id=TEST_ID,
        node_id="tests/test_ping.py::test_latency_within_threshold",
        status=status,
        metrics=(
            Metric(
                name="latency",
                unit="ms",
                authoritative=True,
                samples=(Sample(value=value), Sample(value=value)),
            ),
        ),
        criticality=Criticality.BLOCKING,
        severity=Severity.MEDIUM,
        evidence_state=EvidenceState.NOT_REQUIRED,
    )


def register_telemetry(db, run_id, root, environment):
    path = root / ("telemetry-" + run_id + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "environment_class": environment,
        "captured_at": "2026-09-24T12:00:00+00:00",
        "interface": "wlan0",
        "points": [
            {
                "metric": "rssi_dbm",
                "value": -47,
                "unit": "dBm",
                "environment_class": environment,
                "source": "wpa_cli.signal_poll",
                "interface": "wlan0",
                "captured_at": "2026-09-24T12:00:00+00:00",
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    artifact_service = ArtifactService.from_sqlite(db)
    return artifact_service.register_file(
        run_id=run_id,
        path=path,
        artifact_type=__import__("lib.domain", fromlist=["ArtifactType"]).ArtifactType.TELEMETRY,
    )


def test_v1_api_reads_persisted_run_and_uses_error_envelope(tmp_path):
    db=SQLiteDatabase(tmp_path / "db.sqlite")
    db.initialize()
    service=make_service(db)
    run, attempt=create_run(service, "v1.0")
    record(service, run, attempt, TestResultStatus.PASS, 10)
    app=create_app(tmp_path / "db.sqlite")
    client=app.test_client()

    response=client.get("/api/v1/runs")
    assert response.status_code == 200
    assert response.get_json()["data"]["total"] == 1
    detail=client.get("/api/v1/runs/" + run.run_id)
    assert detail.status_code == 200
    assert detail.get_json()["data"]["run_id"] == run.run_id

    missing=client.get("/api/v1/runs/not-found")
    assert missing.status_code == 404
    assert missing.get_json()["error"]["code"] == "NOT_FOUND"


def test_regression_and_telemetry_are_read_through_canonical_v1(tmp_path):
    db_path=tmp_path / "db.sqlite"
    db=SQLiteDatabase(db_path)
    db.initialize()
    service=make_service(db)
    baseline, base_attempt=create_run(service, "v1.0")
    current, current_attempt=create_run(service, "v1.1")
    record(service, baseline, base_attempt, TestResultStatus.PASS, 10)
    record(service, current, current_attempt, TestResultStatus.PASS, 12)

    root=tmp_path / "results"
    app=create_app(db_path)
    query=app.config["NETREGRESS_QUERY"]
    query.results_root=root
    register_telemetry(db, baseline.run_id, root, "VIRTUAL_WIFI")
    register_telemetry(db, current.run_id, root, "VIRTUAL_WIFI")

    regression=app.test_client().get(
        "/api/v1/regressions?baseline_run_id=" + baseline.run_id + "&current_run_id=" + current.run_id
    )
    body=regression.get_json()
    assert regression.status_code == 200
    assert body["data"]["comparability"] == "COMPARABLE"
    assert body["data"]["assessments"][0]["classification"] == "SOFT_REGRESSION"

    telemetry=app.test_client().get("/api/v1/runs/" + current.run_id + "/telemetry")
    assert telemetry.status_code == 200
    assert telemetry.get_json()["data"]["environment_class"] == "VIRTUAL_WIFI"


def test_artifact_json_fails_closed_after_integrity_change(tmp_path):
    db_path=tmp_path / "db.sqlite"
    db=SQLiteDatabase(db_path)
    db.initialize()
    service=make_service(db)
    run, _=create_run(service, "v1.0")
    root=tmp_path / "results"
    artifact=register_telemetry(db, run.run_id, root, "VIRTUAL_WIFI")
    path=Path(artifact.path)
    path.write_text(path.read_text(encoding="utf-8") + "tampered", encoding="utf-8")

    app=create_app(db_path)
    app.config["NETREGRESS_QUERY"].results_root=root
    response=app.test_client().get("/api/v1/runs/" + run.run_id + "/telemetry")
    assert response.status_code == 200
    assert response.get_json()["data"]["items"] == []


def test_legacy_api_surface_remains_available(tmp_path):
    app=create_app(tmp_path / "db.sqlite")
    response=app.test_client().get("/api/results")
    assert response.status_code == 200

def test_operational_mutation_idempotency_is_durable_and_payload_bound(tmp_path):
    app=create_app(tmp_path / "db.sqlite")
    client=app.test_client()
    payload={"scope":"RELEASE","target_id":"*","issue_code":"NON_PASSING_TEST","reason":"approved"}
    first=client.post("/api/v1/waivers",json=payload,headers={"Idempotency-Key":"waiver-test-1"})
    assert first.status_code == 201
    first_id=first.get_json()["data"]["waiver_id"]

    replay=client.post("/api/v1/waivers",json=payload,headers={"Idempotency-Key":"waiver-test-1"})
    assert replay.status_code == 201
    assert replay.get_json()["data"]["waiver_id"] == first_id

    changed=dict(payload);changed["reason"]="different"
    conflict=client.post("/api/v1/waivers",json=changed,headers={"Idempotency-Key":"waiver-test-1"})
    assert conflict.status_code == 409

