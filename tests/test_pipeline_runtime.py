from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from lib.domain import EnvironmentHealthStatus, EnvironmentSnapshot
from lib.repositories import SQLiteDatabase
from lib.security import AuthManager, Role, UserRecord
from lib.services.configuration_profile_service import ConfigurationProfileService
from lib.services.configuration_schema_registry import ConfigurationSchemaRegistry
from lib.services.device_inventory import DeviceInventoryService
from lib.services.performance_policy_service import PerformancePolicyService
from lib.services.pipeline_runtime import build_pipeline_handlers
from lib.services.pipeline_service import PipelineService
from lib.services.run_service import RunService
from lib.services.test_registry import TestRegistry


def create_database(path):
    database = SQLiteDatabase(path)
    database.initialize()
    now = "2026-11-17T06:00:00+00:00"
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
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-1", "project-1", "Lab", "gns3", 1, "ACTIVE", now, now),
        )
    return database


def create_validation_pipeline(service, inputs):
    created = service.create_pipeline(
        project_id="project-1",
        lab_id="lab-1",
        name="Canonical validation",
        description="Pipeline to canonical Run contract",
        definition={"steps": [{
            "key": "validate",
            "type": "VALIDATION_RUN",
            "timeout_seconds": 30,
            "max_attempts": 1,
            "input": inputs,
        }]},
        actor="owner",
    )
    published = service.publish_revision(
        created["pipeline"]["pipeline_id"], created["revision"]["revision_id"], actor="owner",
    )
    queued = service.enqueue(
        created["pipeline"]["pipeline_id"],
        revision_id=published["revision_id"],
        actor="owner",
    )
    return created, published, queued


class FakeRunProcessManager:
    def __init__(self, database, *, should_complete=True):
        self.database = database
        self.should_complete = should_complete
        self.start_args = None
        self.wait_timeout = None
        self.run_id = None

    def start(self, *, tests, firmware_version, env):
        self.start_args = {"tests": list(tests), "firmware_version": firmware_version, "env": dict(env)}
        if self.should_complete:
            registry = TestRegistry.default()
            run_service = RunService.from_sqlite(self.database, test_registry=registry)
            versions = registry.version_map(tests)
            run, _attempt = run_service.create_run(
                firmware_version=firmware_version,
                lab_id=env["NETREGRESS_LAB_ID"],
                project_id=env["NETREGRESS_PROJECT_ID"],
                validation_profile="Pipeline",
                selected_tests=tests,
                test_definition_versions=versions,
                resolved_config={},
                repository_commit="pipeline-test",
            )
            run.environment = EnvironmentSnapshot(
                snapshot_id="env-" + run.run_id,
                host_os="Linux",
                kernel="test-kernel",
                python_version="3.12",
                repository_commit="pipeline-test",
                configuration_hash=run.configuration_hash,
                tools={},
            )
            metadata = {
                "pipeline_execution_id": env["NETREGRESS_PIPELINE_EXECUTION_ID"],
                "pipeline_step_key": env["NETREGRESS_PIPELINE_STEP_KEY"],
                "pipeline_revision_id": env["NETREGRESS_PIPELINE_REVISION_ID"],
                "pipeline_definition_sha256": env["NETREGRESS_PIPELINE_DEFINITION_SHA256"],
            }
            for key in (
                "NETREGRESS_PERFORMANCE_POLICY_REVISION_ID", "NETREGRESS_PERFORMANCE_POLICY_HASH",
                "NETREGRESS_CONFIGURATION_PROFILE_ID", "NETREGRESS_CONFIGURATION_REVISION_ID",
                "NETREGRESS_CONFIGURATION_HASH", "NETREGRESS_TOPOLOGY_PROFILE_ID",
                "NETREGRESS_TOPOLOGY_REVISION_ID", "NETREGRESS_TOPOLOGY_HASH",
            ):
                if env.get(key):
                    metadata[key.removeprefix("NETREGRESS_").lower()] = env[key]
            run.environment = replace(run.environment, tools={**dict(run.environment.tools), **metadata})
            run_service.run_repository.update(run)
            run_service.begin_lab_health_check(run.run_id)
            run_service.record_environment_health(run.run_id, EnvironmentHealthStatus.HEALTHY)
            run_service.start_run_after_health(run.run_id)
            run_service.complete_run(run.run_id)
            PipelineService(self.database).link_run(env["NETREGRESS_PIPELINE_EXECUTION_ID"], run.run_id)
            self.run_id = run.run_id
        return SimpleNamespace(pid=4321, command=("python", "-m", "pytest"), log_path="/tmp/pipeline-run.log")

    def wait(self, _pid, *, timeout=None):
        self.wait_timeout = timeout
        return 0 if self.should_complete else None


def test_validation_step_runs_registered_suite_and_links_canonical_run(tmp_path):
    database = create_database(tmp_path / "run-link.sqlite")
    pipelines = PipelineService(database)
    manager = FakeRunProcessManager(database)
    _created, revision, queued = create_validation_pipeline(pipelines, {
        "tests": ["wifi.latency.threshold"],
        "firmware_version": "v3.1",
    })
    handlers = build_pipeline_handlers(database, object(), run_process_manager=manager)

    result = pipelines.run_once("worker-1", handlers)
    execution = pipelines.get_execution(queued["execution_id"])
    run = RunService.from_sqlite(database).run_repository.get(manager.run_id)

    assert result["step_status"] == "SUCCEEDED"
    assert execution["linked_run_id"] == manager.run_id
    assert execution["revision_id"] == revision["revision_id"]
    assert run.project_id == "project-1" and run.lab_id == "lab-1"
    assert manager.start_args["tests"] == ["tests/test_ping.py::test_latency_within_threshold"]
    assert manager.start_args["firmware_version"] == "v3.1"
    assert manager.start_args["env"]["NETREGRESS_DATABASE_PATH"] == str(database.path.resolve())
    assert manager.start_args["env"]["NETREGRESS_PIPELINE_EXECUTION_ID"] == queued["execution_id"]
    assert run.environment.tools["pipeline_execution_id"] == queued["execution_id"]
    assert run.environment.tools["pipeline_revision_id"] == revision["revision_id"]
    assert execution["steps"][0]["result"]["run_id"] == manager.run_id
    assert execution["steps"][0]["result"]["run_lifecycle"] == "COMPLETED"


def test_validation_step_pins_assigned_policy_hash_and_evaluates_it(tmp_path):
    database = create_database(tmp_path / "policy-link.sqlite")
    policies = PerformancePolicyService(database)
    profile = policies.create_profile(
        project_id="project-1", name="Pipeline latency", description="Pinned policy",
        scope_type="PROJECT", scope_id="project-1", actor="owner",
    )
    draft = policies.create_revision(profile["policy_profile_id"], definition={"metrics":[{
        "name": "latency", "unit": "ms", "direction": "LOWER_IS_BETTER",
        "target": 20, "warning": 40, "failure": 60,
    }]}, actor="owner")
    published = policies.publish(profile["policy_profile_id"], draft["revision_id"], actor="owner")
    policies.assign(profile["policy_profile_id"], published["revision_id"], lab_id="lab-1", actor="owner")

    pipelines = PipelineService(database)
    manager = FakeRunProcessManager(database)
    _created, _revision, queued = create_validation_pipeline(pipelines, {
        "tests": ["wifi.latency.threshold"],
        "performance_policy_revision_id": published["revision_id"],
    })
    handlers = build_pipeline_handlers(database, object(), run_process_manager=manager)

    result = pipelines.run_once("worker-1", handlers)
    execution = pipelines.get_execution(queued["execution_id"])
    run = RunService.from_sqlite(database).run_repository.get(manager.run_id)

    assert result["step_status"] == "SUCCEEDED"
    assert manager.start_args["env"]["NETREGRESS_PERFORMANCE_POLICY_REVISION_ID"] == published["revision_id"]
    assert manager.start_args["env"]["NETREGRESS_PERFORMANCE_POLICY_HASH"] == published["policy_hash"]
    evaluation = execution["steps"][0]["result"]["performance_policy_evaluation"]
    assert evaluation["revision_id"] == published["revision_id"]
    assert evaluation["policy_hash"] == published["policy_hash"]
    assert evaluation["overall"] == "WARNING"
    assert run.environment.tools["performance_policy_revision_id"] == published["revision_id"]
    assert run.environment.tools["performance_policy_hash"] == published["policy_hash"]


def test_validation_timeout_requires_recovery_and_does_not_auto_replay(tmp_path):
    database = create_database(tmp_path / "timeout.sqlite")
    pipelines = PipelineService(database)
    manager = FakeRunProcessManager(database, should_complete=False)
    _created, _revision, queued = create_validation_pipeline(pipelines, {
        "tests": ["wifi.latency.threshold"],
    })
    handlers = build_pipeline_handlers(database, object(), run_process_manager=manager)

    result = pipelines.run_once("worker-1", handlers)
    execution = pipelines.get_execution(queued["execution_id"])

    assert result["step_status"] == "RECOVERY_REQUIRED"
    assert execution["status"] == "RECOVERY_REQUIRED"
    assert execution["steps"][0]["max_attempts"] == 1
    assert execution["steps"][0]["result"]["details"]["process_id"] == 4321
    with pytest.raises(ValueError, match="explicit recovery confirmation"):
        pipelines.recover(queued["execution_id"], confirmed=False, actor="owner")


def test_validation_definition_requires_paired_configuration_and_topology_refs():
    with pytest.raises(ValueError, match="must be provided together"):
        PipelineService.normalize_definition({"steps": [{
            "key": "validate", "type": "VALIDATION_RUN",
            "input": {"tests": ["wifi.latency.threshold"], "configuration_profile_id": "profile-1"},
        }]})


def test_pipeline_api_enforces_rbac_and_idempotent_create_enqueue(tmp_path):
    from dashboard.app import create_app

    password = "pipeline-test-password-2026"
    database_path = tmp_path / "pipeline-api.sqlite"
    create_database(database_path)
    auth = AuthManager((
        UserRecord("owner", AuthManager.password_hash(password), Role.OWNER, ("project-1",)),
        UserRecord("operator", AuthManager.password_hash(password), Role.OPERATOR, ("project-1",)),
        UserRecord("viewer", AuthManager.password_hash(password), Role.VIEWER, ("project-1",)),
    ), required=True)
    app = create_app(database_path, auth_manager=auth)
    app.config.update(TESTING=True)

    def login(username):
        client = app.test_client()
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200
        return client, response.get_json()["data"]["csrf_token"]

    owner, owner_csrf = login("owner")
    operator, operator_csrf = login("operator")
    viewer, viewer_csrf = login("viewer")
    definition = {"steps": [{"key": "inspect", "type": "PROVIDER_RECONCILE",
                             "input": {"profile_id": "topology-1", "revision_id": "revision-1"}}]}
    create_payload = {
        "project_id": "project-1", "lab_id": "lab-1", "name": "Pipeline API",
        "description": "RBAC and idempotency", "definition": definition,
    }
    create_headers = {"X-CSRF-Token": owner_csrf, "Idempotency-Key": "pipeline-create-01"}
    created = owner.post("/api/v1/pipelines", json=create_payload, headers=create_headers)
    created_replay = owner.post("/api/v1/pipelines", json=create_payload, headers=create_headers)
    assert created.status_code == 201 and created_replay.status_code == 201
    pipeline_id = created.get_json()["data"]["pipeline"]["pipeline_id"]
    revision_id = created.get_json()["data"]["revision"]["revision_id"]
    assert created_replay.get_json()["data"]["pipeline"]["pipeline_id"] == pipeline_id

    published = owner.post(
        f"/api/v1/pipelines/{pipeline_id}/publish",
        json={"revision_id": revision_id},
        headers={"X-CSRF-Token": owner_csrf, "Idempotency-Key": "pipeline-publish-01"},
    )
    assert published.status_code == 200

    denied_authoring = operator.post(
        "/api/v1/pipelines",
        json={**create_payload, "name": "Operator cannot author"},
        headers={"X-CSRF-Token": operator_csrf, "Idempotency-Key": "operator-create-01"},
    )
    assert denied_authoring.status_code == 403
    assert operator.get("/api/v1/pipelines?project_id=project-1").status_code == 200

    enqueue_headers = {"X-CSRF-Token": operator_csrf, "Idempotency-Key": "pipeline-enqueue-01"}
    queued = operator.post(
        f"/api/v1/pipelines/{pipeline_id}/executions",
        json={"revision_id": revision_id},
        headers=enqueue_headers,
    )
    queued_replay = operator.post(
        f"/api/v1/pipelines/{pipeline_id}/executions",
        json={"revision_id": revision_id},
        headers=enqueue_headers,
    )
    assert queued.status_code == 202 and queued_replay.status_code == 202
    assert queued.get_json()["data"]["execution_id"] == queued_replay.get_json()["data"]["execution_id"]

    denied_execution = viewer.post(
        f"/api/v1/pipelines/{pipeline_id}/executions",
        json={"revision_id": revision_id},
        headers={"X-CSRF-Token": viewer_csrf, "Idempotency-Key": "viewer-enqueue-01"},
    )
    assert denied_execution.status_code == 403


def test_validation_run_binds_managed_device_and_resolves_published_configuration_values(tmp_path):
    database = create_database(tmp_path / "managed-device-run.sqlite")
    schemas = ConfigurationSchemaRegistry(database)
    schema = schemas.register(
        project_id="project-1", schema_id="runner.settings", version=1,
        name="Runner settings", actor="owner", definition={
            "type": "object", "required": ["ssid", "channel"], "additionalProperties": False,
            "properties": {
                "ssid": {"type": "string", "minLength": 1, "maxLength": 32},
                "channel": {"type": "integer", "minimum": 1, "maximum": 165},
            },
        },
    )
    profiles = ConfigurationProfileService(database, schemas)
    profile = profiles.create_profile(
        project_id="project-1", name="Pipeline config", description="", scope_type="PROJECT",
        scope_id="project-1", schema_record_id=schema["schema_record_id"], actor="owner",
    )
    draft = profiles.create_revision(
        profile["profile_id"], values={"ssid": "PipelineNet", "channel": 44}, actor="owner",
    )
    published = profiles.publish(profile["profile_id"], draft["revision_id"], actor="owner")
    device = DeviceInventoryService(database).create({
        "project_id": "project-1", "lab_id": "lab-1", "device_key": "client_vm",
        "name": "Managed Client", "device_type": "CLIENT", "host": "192.0.2.50",
        "port": 2222, "username": "runner",
    }, actor="owner")

    class VaultMetadata:
        def get(self, credential_id):
            if credential_id != "ssh-credential-1":
                return None
            return {
                "credential_id": credential_id, "project_id": "project-1",
                "device_id": device["device_id"], "credential_type": "SSH_PASSWORD",
                "status": "ACTIVE", "username": "vault-runner",
            }

    pipelines = PipelineService(database)
    manager = FakeRunProcessManager(database)
    _created, _revision, queued = create_validation_pipeline(pipelines, {
        "tests": ["wifi.latency.threshold"],
        "configuration_profile_id": profile["profile_id"],
        "configuration_revision_id": published["revision_id"],
        "device_id": device["device_id"],
        "ssh_credential_id": "ssh-credential-1",
    })
    handlers = build_pipeline_handlers(database, VaultMetadata(), run_process_manager=manager)

    result = pipelines.run_once("worker-1", handlers)
    execution = pipelines.get_execution(queued["execution_id"])
    environment = manager.start_args["env"]

    assert result["step_status"] == "SUCCEEDED"
    assert environment["NETREGRESS_CONFIGURATION_PROFILE_ID"] == profile["profile_id"]
    assert environment["NETREGRESS_CONFIGURATION_REVISION_ID"] == published["revision_id"]
    assert environment["NETREGRESS_CONFIGURATION_SCOPE_TYPE"] == "PROJECT"
    assert json.loads(environment["NETREGRESS_CONFIGURATION_VALUES_JSON"]) == {
        "ssid": "PipelineNet", "channel": 44,
    }
    assert environment["NETREGRESS_DEVICE_ID"] == "client_vm"
    assert environment["NETREGRESS_MANAGED_DEVICE_ID"] == device["device_id"]
    assert environment["NETREGRESS_DEVICE_HOST"] == "192.0.2.50"
    assert environment["NETREGRESS_DEVICE_PORT"] == "2222"
    assert environment["NETREGRESS_DEVICE_USERNAME"] == "vault-runner"
    assert environment["NETREGRESS_DEVICE_SSH_CREDENTIAL_ID"] == "ssh-credential-1"
    assert execution["steps"][0]["result"]["references"]["device"]["device_id"] == device["device_id"]
