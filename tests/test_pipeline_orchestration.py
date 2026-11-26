from __future__ import annotations

import sqlite3
import pytest

from lib.repositories import SQLiteDatabase
from lib.services.pipeline_service import (
    PipelineConflict, PipelineError, PipelineRetryableError, PipelineService,
)


@pytest.fixture
def pipeline(tmp_path):
    database = SQLiteDatabase(tmp_path / "pipeline.sqlite")
    database.initialize()
    now = "2026-11-16T10:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute("INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)", ("org-1", "org", "Organization", "ACTIVE", now, now))
        connection.execute("INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", ("project-1", "org-1", "project", "Project", "ACTIVE", now, now))
        connection.execute("INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", ("lab-1", "project-1", "Lab", "gns3", 1, "ACTIVE", now, now))
    return database, PipelineService(database)


def definition():
    return {"steps": [{
        "key": "provision", "type": "WIFI_LAB_PROVISION", "name": "Provision reference lab",
        "timeout_seconds": 600, "max_attempts": 1, "input": {"confirmed": True},
    }]}


def published_pipeline(service):
    created = service.create_pipeline(
        project_id="project-1", lab_id="lab-1", name="Reference Wi-Fi",
        description="Protected Wi-Fi validation pipeline", definition=definition(), actor="owner",
    )
    service.publish_revision(created["pipeline"]["pipeline_id"], created["revision"]["revision_id"], actor="owner")
    return created["pipeline"], created["revision"]


def test_pipeline_definitions_are_scoped_and_published_revisions_are_immutable(pipeline):
    database, service = pipeline
    profile, revision = published_pipeline(service)
    assert profile["lab_id"] == "lab-1"
    assert service.get_revision(revision["revision_id"])["status"] == "PUBLISHED"
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="published pipeline revisions are immutable"):
            connection.execute("UPDATE pipeline_revisions SET definition_json='{}' WHERE revision_id=?", (revision["revision_id"],))
        with pytest.raises(sqlite3.IntegrityError, match="pipeline revision history cannot be deleted"):
            connection.execute("DELETE FROM pipeline_revisions WHERE revision_id=?", (revision["revision_id"],))


@pytest.mark.parametrize("value,match", [
    ({"steps": []}, "between 1 and"),
    ({"steps": [{"key": "bad key", "type": "WIFI_LAB_PROVISION", "input": {"confirmed": True}}]}, "invalid or duplicated"),
    ({"steps": [{"key": "x", "type": "ARBITRARY_SHELL", "input": {}}]}, "not supported"),
    ({"steps": [{"key": "x", "type": "WIFI_LAB_PROVISION", "input": {"confirmed": True, "command": "rm -rf"}}]}, "exactly"),
    ({"steps": [{"key": "x", "type": "WIFI_LAB_PROVISION", "input": {"confirmed": True}}, {"key": "x", "type": "WIFI_LAB_PROVISION", "input": {"confirmed": True}}]}, "invalid or duplicated"),
])
def test_pipeline_definition_validation_fails_closed(value, match):
    with pytest.raises(PipelineError, match=match):
        PipelineService.normalize_definition(value)


def test_pipeline_enqueue_persists_steps_and_worker_attempts(pipeline):
    _database, service = pipeline
    profile, revision = published_pipeline(service)
    queued = service.enqueue(profile["pipeline_id"], revision_id=revision["revision_id"], actor="owner")
    assert queued["status"] == "QUEUED" and len(queued["steps"]) == 1
    result = service.run_once("worker-1", {
        "WIFI_LAB_PROVISION": lambda execution, _step: {"status": "APPLIED", "lab_id": execution["lab_id"]},
    })
    assert result["step_status"] == "SUCCEEDED"
    final = service.get_execution(queued["execution_id"])
    assert final["status"] == "SUCCEEDED"
    assert final["steps"][0]["attempt_count"] == 1
    assert final["attempts"][0]["status"] == "SUCCEEDED"


def test_retry_requires_handler_classification_and_is_bounded(pipeline):
    database, service = pipeline
    profile, _revision = published_pipeline(service)
    draft = service.create_revision(profile["pipeline_id"], definition={
        "steps": [{
            "key": "inspect", "type": "PROVIDER_RECONCILE", "max_attempts": 2,
            "input": {"profile_id": "topology-1", "revision_id": "revision-1"},
        }],
    }, actor="owner")
    service.publish_revision(profile["pipeline_id"], draft["revision_id"], actor="owner")
    queued = service.enqueue(profile["pipeline_id"], revision_id=draft["revision_id"], actor="owner")
    result = service.run_once("worker-1", {
        "PROVIDER_RECONCILE": lambda _execution, _step: (_ for _ in ()).throw(PipelineRetryableError("temporary read error")),
    })
    assert result["step_status"] == "RETRY_WAIT"
    with database.transaction(immediate=True) as connection:
        connection.execute("UPDATE pipeline_steps SET next_attempt_at='2000-01-01T00:00:00+00:00' WHERE execution_id=?", (queued["execution_id"],))
    result = service.run_once("worker-1", {"PROVIDER_RECONCILE": lambda _e, _s: {"status": "IN_SYNC"}})
    assert result["step_status"] == "SUCCEEDED"
    assert service.get_execution(queued["execution_id"])["status"] == "SUCCEEDED"


def test_expired_worker_lease_requires_explicit_recovery(pipeline):
    database, service = pipeline
    profile, revision = published_pipeline(service)
    queued = service.enqueue(profile["pipeline_id"], revision_id=revision["revision_id"], actor="owner")
    with database.transaction(immediate=True) as connection:
        connection.execute("UPDATE pipeline_executions SET status='RUNNING',worker_id='dead-worker',lease_expires_at='2000-01-01T00:00:00+00:00' WHERE execution_id=?", (queued["execution_id"],))
        connection.execute("UPDATE pipeline_steps SET status='RUNNING',worker_id='dead-worker',lease_expires_at='2000-01-01T00:00:00+00:00',attempt_count=1 WHERE execution_id=?", (queued["execution_id"],))
        connection.execute("""INSERT INTO pipeline_step_attempts(step_attempt_id,execution_id,step_key,attempt_number,status,worker_id,started_at,completed_at,result_json,error_summary) VALUES('attempt-dead',?,'provision',1,'RUNNING','dead-worker','2000-01-01T00:00:00+00:00',NULL,'{}',NULL)""", (queued["execution_id"],))
    result = service.run_once("worker-2", {"WIFI_LAB_PROVISION": lambda _e, _s: {"status": "APPLIED"}})
    assert result["status"] == "RECOVERY_REQUIRED"
    assert service.get_execution(queued["execution_id"])["steps"][0]["status"] == "RECOVERY_REQUIRED"
    with pytest.raises(PipelineConflict, match="explicit recovery confirmation"):
        service.recover(queued["execution_id"], confirmed=False, actor="owner")
    recovered = service.recover(queued["execution_id"], confirmed=True, actor="owner")
    assert recovered["status"] == "QUEUED"
    assert recovered["steps"][0]["max_attempts"] == 1  # Published step policy remains immutable.
    resumed = service.run_once("worker-3", {"WIFI_LAB_PROVISION": lambda _e, _s: {"status": "APPLIED"}})
    assert resumed["step_status"] == "SUCCEEDED"
    assert service.get_execution(queued["execution_id"])["status"] == "SUCCEEDED"


def test_pipeline_cancel_does_not_interrupt_running_provider_step(pipeline):
    database, service = pipeline
    profile, revision = published_pipeline(service)
    queued = service.enqueue(profile["pipeline_id"], revision_id=revision["revision_id"], actor="owner")
    with database.transaction(immediate=True) as connection:
        connection.execute("UPDATE pipeline_executions SET status='RUNNING',worker_id='worker-1',lease_expires_at='2099-01-01T00:00:00+00:00' WHERE execution_id=?", (queued["execution_id"],))
        connection.execute("UPDATE pipeline_steps SET status='RUNNING',worker_id='worker-1',lease_expires_at='2099-01-01T00:00:00+00:00' WHERE execution_id=?", (queued["execution_id"],))
    cancelling = service.cancel(queued["execution_id"], actor="owner")
    assert cancelling["status"] == "CANCELLING"
    assert cancelling["steps"][0]["status"] == "RUNNING"


def test_pipeline_rejects_secret_values_not_opaque_reference_ids():
    with pytest.raises(PipelineError, match="secret material"):
        PipelineService.normalize_definition({"steps": [{
            "key": "bad", "type": "WIFI_LAB_PROVISION", "input": {"confirmed": True, "api_token": "plaintext"},
        }]})


def test_pipeline_run_link_database_guard_rejects_cross_project_lab_run(pipeline):
    database, service = pipeline
    from lib.services.run_service import RunService

    now = "2026-11-17T06:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-2", "org-1", "project-2", "Other Project", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-2", "project-2", "Other Lab", "gns3", 1, "ACTIVE", now, now),
        )
    profile, revision = published_pipeline(service)
    queued = service.enqueue(profile["pipeline_id"], revision_id=revision["revision_id"], actor="owner")
    run_service = RunService.from_sqlite(database)
    run, _attempt = run_service.create_run(
        firmware_version="v1.0", lab_id="lab-2", project_id="project-2",
        validation_profile="Smoke", selected_tests=["wifi.latency.threshold"],
        test_definition_versions={"wifi.latency.threshold": "1.0"},
        resolved_config={}, repository_commit="test-commit",
    )
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="same Project/Lab"):
            connection.execute(
                "UPDATE pipeline_executions SET linked_run_id=? WHERE execution_id=?",
                (run.run_id, queued["execution_id"]),
            )


def _graph_step(key, step_type="PROVIDER_RECONCILE", dependencies=None):
    item = {
        "key": key,
        "type": step_type,
        "name": key.replace("_", " ").title(),
        "timeout_seconds": 30,
        "max_attempts": 1,
        "input": ({"confirmed": True} if step_type == "WIFI_LAB_PROVISION"
                  else {"profile_id": "top-profile", "revision_id": "top-revision"}),
    }
    if dependencies is not None:
        item["depends_on"] = dependencies
    return item


def test_pipeline_graph_validation_supports_dag_and_conditional_outcomes():
    normalized = PipelineService.normalize_definition({"steps": [
        _graph_step("prepare", "WIFI_LAB_PROVISION"),
        _graph_step("on_success", dependencies=[{"step_key": "prepare", "outcome": "SUCCESS"}]),
        _graph_step("on_failure", dependencies=[{"step_key": "prepare", "outcome": "FAILURE"}]),
        _graph_step("after_any_result", dependencies=[{"step_key": "prepare", "outcome": "COMPLETED"}]),
        _graph_step("independent", dependencies=[]),
    ]})
    assert [item["key"] for item in normalized["steps"]] == [
        "prepare", "on_success", "on_failure", "after_any_result", "independent"
    ]
    assert normalized["steps"][2]["depends_on"] == [
        {"step_key": "prepare", "outcome": "FAILURE"}
    ]
    assert normalized["steps"][4]["depends_on"] == []


@pytest.mark.parametrize("dependencies,match", [
    ([{"step_key": "missing", "outcome": "SUCCESS"}], "unknown step"),
    ([{"step_key": "branch", "outcome": "SUCCESS"}], "same step"),
    ([{"step_key": "root", "outcome": "UNKNOWN"}], "must be SUCCESS"),
    ([{"step_key": "root", "outcome": "SUCCESS"}, {"step_key": "root", "outcome": "FAILURE"}], "duplicated"),
])
def test_pipeline_graph_validation_rejects_invalid_dependency_edges(dependencies, match):
    definition = {"steps": [
        _graph_step("root", "WIFI_LAB_PROVISION"),
        _graph_step("branch", dependencies=dependencies),
    ]}
    with pytest.raises(PipelineError, match=match):
        PipelineService.normalize_definition(definition)


def test_pipeline_graph_validation_rejects_null_dependency_entries():
    definition = {"steps": [
        _graph_step("root", "WIFI_LAB_PROVISION"),
        _graph_step("branch", dependencies=[None]),
    ]}
    with pytest.raises(PipelineError, match="must contain only step_key and outcome"):
        PipelineService.normalize_definition(definition)


def test_pipeline_graph_validation_rejects_cycles_even_with_forward_references():
    definition = {"steps": [
        _graph_step("first", dependencies=[{"step_key": "second", "outcome": "SUCCESS"}]),
        _graph_step("second", dependencies=[{"step_key": "first", "outcome": "SUCCESS"}]),
    ]}
    with pytest.raises(PipelineError, match="cycle"):
        PipelineService.normalize_definition(definition)


def test_pipeline_graph_defaults_old_definitions_to_sequential_edges():
    normalized = PipelineService.normalize_definition({"steps": [
        _graph_step("first", "WIFI_LAB_PROVISION"),
        _graph_step("second"),
        _graph_step("third"),
    ]})
    assert normalized["steps"][0]["depends_on"] == []
    assert normalized["steps"][1]["depends_on"] == [
        {"step_key": "first", "outcome": "SUCCESS"}
    ]
    assert normalized["steps"][2]["depends_on"] == [
        {"step_key": "second", "outcome": "SUCCESS"}
    ]


def test_pipeline_worker_executes_failure_and_completed_branches(pipeline):
    _database, service = pipeline
    profile, _revision = published_pipeline(service)
    definition_value = {"steps": [
        _graph_step("prepare", "WIFI_LAB_PROVISION"),
        _graph_step("success_branch", dependencies=[{"step_key": "prepare", "outcome": "SUCCESS"}]),
        _graph_step("failure_branch", dependencies=[{"step_key": "prepare", "outcome": "FAILURE"}]),
        _graph_step("completed_branch", dependencies=[{"step_key": "prepare", "outcome": "COMPLETED"}]),
        _graph_step("independent_root", dependencies=[]),
    ]}
    draft = service.create_revision(profile["pipeline_id"], definition=definition_value, actor="owner")
    service.publish_revision(profile["pipeline_id"], draft["revision_id"], actor="owner")
    queued = service.enqueue(profile["pipeline_id"], revision_id=draft["revision_id"], actor="owner")

    first = service.run_once("graph-worker", {
        "WIFI_LAB_PROVISION": lambda _e, _s: (_ for _ in ()).throw(RuntimeError("expected test failure")),
    })
    assert first["step_key"] == "prepare" and first["step_status"] == "FAILED"

    second = service.run_once("graph-worker", {
        "PROVIDER_RECONCILE": lambda _e, step: {"executed": step["step_key"]},
    })
    assert second["step_key"] == "failure_branch"
    assert second["step_status"] == "SUCCEEDED"

    third = service.run_once("graph-worker", {
        "PROVIDER_RECONCILE": lambda _e, step: {"executed": step["step_key"]},
    })
    assert third["step_key"] == "completed_branch"
    assert third["step_status"] == "SUCCEEDED"

    fourth = service.run_once("graph-worker", {
        "PROVIDER_RECONCILE": lambda _e, step: {"executed": step["step_key"]},
    })
    assert fourth["step_key"] == "independent_root"
    assert fourth["step_status"] == "SUCCEEDED"

    final = service.get_execution(queued["execution_id"])
    statuses = {item["step_key"]: item["status"] for item in final["steps"]}
    assert statuses == {
        "prepare": "FAILED", "success_branch": "SKIPPED",
        "failure_branch": "SUCCEEDED", "completed_branch": "SUCCEEDED",
        "independent_root": "SUCCEEDED",
    }
    assert final["status"] == "FAILED"


def test_pipeline_graph_recovery_required_blocks_other_graph_branches(pipeline):
    _database, service = pipeline
    profile, _revision = published_pipeline(service)
    definition_value = {"steps": [
        _graph_step("uncertain", "WIFI_LAB_PROVISION"),
        _graph_step("independent", dependencies=[]),
    ]}
    draft = service.create_revision(profile["pipeline_id"], definition=definition_value, actor="owner")
    service.publish_revision(profile["pipeline_id"], draft["revision_id"], actor="owner")
    queued = service.enqueue(profile["pipeline_id"], revision_id=draft["revision_id"], actor="owner")

    from lib.services.pipeline_service import PipelineRecoveryRequired
    result = service.run_once("graph-worker", {
        "WIFI_LAB_PROVISION": lambda _e, _s: (_ for _ in ()).throw(
            PipelineRecoveryRequired("provider response lost")
        ),
    })
    assert result["execution_status"] == "RECOVERY_REQUIRED"
    assert service.run_once("graph-worker", {"WIFI_LAB_PROVISION": lambda _e, _s: {"unexpected": True}}) is None
    final = service.get_execution(queued["execution_id"])
    assert final["status"] == "RECOVERY_REQUIRED"
    assert {step["step_key"]: step["status"] for step in final["steps"]} == {
        "uncertain": "RECOVERY_REQUIRED", "independent": "PENDING",
    }
