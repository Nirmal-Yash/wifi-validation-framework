from __future__ import annotations

import json
from pathlib import Path

from lib.domain import (
    ArtifactType,
    Criticality,
    EvidenceState,
    EnvironmentHealthStatus,
    BusinessOutcome,
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
from lib.security import AuthManager, Role, UserRecord


TEST_ID = "wifi.latency.threshold"

def make_app(db_path):
    return create_app(db_path, auth_manager=AuthManager((), required=False))


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
                samples=(Sample(value=value), Sample(value=value), Sample(value=value)),
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
    app=make_app(tmp_path / "db.sqlite")
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
    for target in (baseline, current):
        service.begin_lab_health_check(target.run_id)
        service.record_environment_health(target.run_id, EnvironmentHealthStatus.HEALTHY)
        service.start_run_after_health(target.run_id)
        service.complete_run(target.run_id, BusinessOutcome.VALIDATED)

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


def test_release_gate_is_available_through_canonical_v1(tmp_path):
    db_path = tmp_path / "db.sqlite"
    db = SQLiteDatabase(db_path)
    db.initialize()
    service = make_service(db)
    baseline, base_attempt = create_run(service, "v1.0")
    current, current_attempt = create_run(service, "v1.1")
    record(service, baseline, base_attempt, TestResultStatus.PASS, 10)
    record(service, current, current_attempt, TestResultStatus.PASS, 10)
    service.begin_lab_health_check(baseline.run_id)
    service.record_environment_health(baseline.run_id, __import__("lib.domain", fromlist=["EnvironmentHealthStatus"]).EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(baseline.run_id)
    service.complete_run(baseline.run_id, __import__("lib.domain", fromlist=["BusinessOutcome"]).BusinessOutcome.VALIDATED)
    service.begin_lab_health_check(current.run_id)
    service.record_environment_health(current.run_id, __import__("lib.domain", fromlist=["EnvironmentHealthStatus"]).EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(current.run_id)
    service.complete_run(current.run_id, __import__("lib.domain", fromlist=["BusinessOutcome"]).BusinessOutcome.VALIDATED)
    app = create_app(db_path)
    response = app.test_client().get(
        "/api/v1/runs/" + current.run_id + "/release-gate?baseline_run_id=" + baseline.run_id
    )
    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["current_run_id"] == current.run_id
    assert body["baseline_run_id"] == baseline.run_id
    assert "accepted" in body


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



def test_retry_api_starts_new_process_with_source_run_lineage(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import dashboard.api_v1 as api_module

    db_path = tmp_path / "retry-api.db"
    database = SQLiteDatabase(db_path)
    database.initialize()
    service = make_service(database)
    source, source_attempt = create_run(service, "v1.0")
    record(service, source, source_attempt, TestResultStatus.PASS, 10)
    from lib.domain import EnvironmentHealthStatus, BusinessOutcome
    service.begin_lab_health_check(source.run_id)
    service.record_environment_health(source.run_id, EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(source.run_id)
    service.complete_run(source.run_id, BusinessOutcome.VALIDATED)
    observed = {}

    class FakeRunProcessManager:
        def __init__(self, root):
            observed["root"] = root

        def start(self, **kwargs):
            observed["start_kwargs"] = kwargs
            return SimpleNamespace(pid=4321, command=("python", "-m", "pytest"))

    monkeypatch.setattr(api_module, "RunProcessManager", FakeRunProcessManager)
    response = make_app(db_path).test_client().post(
        f"/api/v1/runs/{source.run_id}/retry",
        headers={"Idempotency-Key": "retry-source-lineage-1"},
    )

    assert response.status_code == 202
    assert response.get_json()["data"]["source_run_id"] == source.run_id
    assert observed["start_kwargs"]["env"] == {
        "NETREGRESS_SOURCE_RUN_ID": source.run_id,
        "NETREGRESS_DATABASE_PATH": str(db_path.resolve()),
        "TEST_DB_PATH": str(db_path.resolve()),
    }


def test_retry_api_rejects_nonterminal_source_run(tmp_path):
    db_path = tmp_path / "retry-active-api.db"
    database = SQLiteDatabase(db_path)
    database.initialize()
    service = make_service(database)
    source, _ = create_run(service, "v1.0")

    response = make_app(db_path).test_client().post(
        f"/api/v1/runs/{source.run_id}/retry",
        headers={"Idempotency-Key": "retry-active-lineage-1"},
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "RUN_NOT_TERMINAL"



def register_download_artifact(db, run_id, root, sensitivity):
    path = root / ("download-" + run_id + ".txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("artifact payload", encoding="utf-8")
    return ArtifactService.from_sqlite(db).register_file(
        run_id=run_id,
        path=path,
        artifact_type=ArtifactType.OTHER,
        sensitivity_class=sensitivity,
    )


def test_remote_artifact_download_requires_configured_bearer_token(tmp_path, monkeypatch):
    db_path = tmp_path / "remote-artifact.sqlite"
    db = SQLiteDatabase(db_path)
    db.initialize()
    run, _ = create_run(make_service(db), "v1.0")
    root = tmp_path / "results"
    artifact = register_download_artifact(db, run.run_id, root, "INTERNAL")
    app = make_app(db_path)
    app.config["NETREGRESS_QUERY"].results_root = root
    client = app.test_client()
    remote = {"REMOTE_ADDR": "203.0.113.25"}

    monkeypatch.delenv("NETREGRESS_DASHBOARD_TOKEN", raising=False)
    denied = client.get(
        f"/api/v1/artifacts/{artifact.artifact_id}/download",
        environ_base=remote,
    )
    assert denied.status_code == 403

    monkeypatch.setenv("NETREGRESS_DASHBOARD_TOKEN", "download-access-token")
    invalid = client.get(
        f"/api/v1/artifacts/{artifact.artifact_id}/download",
        headers={"Authorization": "Bearer wrong-token"},
        environ_base=remote,
    )
    assert invalid.status_code == 403

    allowed = client.get(
        f"/api/v1/artifacts/{artifact.artifact_id}/download",
        headers={"Authorization": "Bearer download-access-token"},
        environ_base=remote,
    )
    assert allowed.status_code == 200
    assert allowed.data == b"artifact payload"


def test_remote_browser_session_can_download_internal_artifact_without_bearer_token(tmp_path, monkeypatch):
    db_path = tmp_path / "remote-browser-artifact.sqlite"
    db = SQLiteDatabase(db_path)
    db.initialize()
    run, _ = create_run(make_service(db), "v1.0")
    root = tmp_path / "results"
    artifact = register_download_artifact(db, run.run_id, root, "INTERNAL")
    password = "phase-l-browser-password"
    auth = AuthManager((UserRecord("operator", AuthManager.password_hash(password), Role.OPERATOR),), required=True)
    app = create_app(db_path, auth_manager=auth)
    app.config["NETREGRESS_QUERY"].results_root = root
    client = app.test_client()
    assert client.post("/api/v1/auth/login", json={"username":"operator","password":password}).status_code == 200
    monkeypatch.delenv("NETREGRESS_DASHBOARD_TOKEN", raising=False)
    response = client.get(f"/api/v1/artifacts/{artifact.artifact_id}/download", environ_base={"REMOTE_ADDR":"203.0.113.25"})
    assert response.status_code == 200 and response.data == b"artifact payload"


def test_admin_can_inspect_offline_sync_queue_without_payload_contents(tmp_path):
    app = make_app(tmp_path / "sync-queue.sqlite")
    response = app.test_client().get("/api/v1/sync/queue")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["summary"]["total"] == 0
    assert data["items"] == []


def test_waiver_list_returns_only_active_records(tmp_path):
    app = make_app(tmp_path / "waivers.sqlite")
    client = app.test_client()
    created = client.post("/api/v1/waivers", json={"scope":"RELEASE","target_id":"*","issue_code":"NO_BASELINE","reason":"approved","expires_at":"2999-01-01T00:00:00+00:00"}, headers={"Idempotency-Key":"phase-l-waiver-create"})
    assert created.status_code == 201
    listed = client.get("/api/v1/waivers")
    assert listed.status_code == 200
    assert [item["issue_code"] for item in listed.get_json()["data"]["items"]] == ["NO_BASELINE"]
    expired = client.post("/api/v1/waivers", json={"scope":"TEST","target_id":"test-1","issue_code":"X","reason":"expired","expires_at":"2000-01-01T00:00:00+00:00"}, headers={"Idempotency-Key":"phase-l-waiver-expired"})
    assert expired.status_code == 400


def test_sensitive_artifact_download_requires_admin_role(tmp_path):
    db_path = tmp_path / "sensitive-artifact.sqlite"
    db = SQLiteDatabase(db_path)
    db.initialize()
    run, _ = create_run(make_service(db), "v1.0")
    root = tmp_path / "results"
    artifact = register_download_artifact(db, run.run_id, root, "SENSITIVE")
    password = "phase-k-test-password"
    auth = AuthManager(
        (
            UserRecord("operator", AuthManager.password_hash(password), Role.OPERATOR),
            UserRecord("admin", AuthManager.password_hash(password), Role.ADMIN),
        ),
        required=True,
    )
    app = create_app(db_path, auth_manager=auth)
    app.config["NETREGRESS_QUERY"].results_root = root

    operator = app.test_client()
    assert operator.post(
        "/api/v1/auth/login", json={"username": "operator", "password": password}
    ).status_code == 200
    denied = operator.get(f"/api/v1/artifacts/{artifact.artifact_id}/download")
    assert denied.status_code == 403

    admin = app.test_client()
    assert admin.post(
        "/api/v1/auth/login", json={"username": "admin", "password": password}
    ).status_code == 200
    allowed = admin.get(f"/api/v1/artifacts/{artifact.artifact_id}/download")
    assert allowed.status_code == 200
    assert allowed.data == b"artifact payload"
