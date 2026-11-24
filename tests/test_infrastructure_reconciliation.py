from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
import hashlib

import pytest

from lib.repositories import SQLiteDatabase
from lib.services.infrastructure_automation import (
    InfrastructureAutomationConflict,
    InfrastructureAutomationError,
    InfrastructureAutomationNotFound,
    InfrastructureAutomationService,
)
from lib.services.resource_lock import ResourceLockManager
from lib.services.topology_studio import TopologyStudioService


class ReconciliationRunner:
    def __init__(self):
        self.state = {"values": {"root_module": {"resources": [], "child_modules": []}}}
        self.drift = []
        self.apply_success = True
        self.apply_calls = 0
        self.plan_calls = []

    def prepare(self, *, workspace):
        return {"valid": True, "version": "OpenTofu v1.9.0"}

    def plan(self, *, workspace, plan_file, destroy=False, refresh_only=False):
        self.plan_calls.append({"refresh_only": refresh_only, "destroy": destroy})
        target = workspace / plan_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            b"refresh-plan" if refresh_only else (
                b"destroy-plan" if destroy else b"apply-plan"
            )
        )
        return {
            "valid": True,
            "has_changes": True,
            "plan_json": {
                "resource_drift": list(self.drift) if refresh_only else [],
                "resource_changes": [{
                    "address": "aws_instance.router",
                    "type": "aws_instance",
                    "change": {"actions": ["update"]},
                }] if not refresh_only else [],
                "output_changes": {},
            },
        }

    def state_show(self, *, workspace):
        return self.state

    def state_list(self, *, workspace):
        return sorted(
            item["resource_address"]
            for item in InfrastructureAutomationService._state_resources(self.state)
        )

    def apply(self, *, workspace, plan_file):
        self.apply_calls += 1
        return {
            "success": self.apply_success,
            "exit_code": 0 if self.apply_success else 1,
            "timed_out": False,
        }


@pytest.fixture
def infrastructure_environment(tmp_path):
    database = SQLiteDatabase(tmp_path / "infrastructure-p12.sqlite")
    database.initialize()
    now = datetime.now(timezone.utc).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-1", "org", "Organization", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-1", "org-1", "main", "Main Project", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-1", "project-1", "Primary Lab", "gns3", 1, "ACTIVE", now, now),
        )
    module_root = tmp_path / "modules"
    module = module_root / "fixture"
    module.mkdir(parents=True)
    (module / "main.tf").write_text('terraform { required_version = ">= 1.8.0" }\n', encoding="utf-8")
    runner = ReconciliationRunner()
    service = InfrastructureAutomationService(
        database, runner=runner, module_root=module_root,
        state_root=tmp_path / "private-state",
        resource_lock_manager=ResourceLockManager(tmp_path / "shared-locks"),
    )
    workspace = service.create_workspace(
        project_id="project-1", lab_id="lab-1", name="Infrastructure",
        module_key="fixture", variables={"region": "fixture-region"}, actor="creator",
    )
    topology = TopologyStudioService(database)
    return {
        "database": database, "runner": runner, "service": service,
        "topology": topology, "workspace": workspace,
    }


def _state(*resources):
    return {
        "format_version": "1.0",
        "terraform_version": "1.9.0",
        "values": {
            "root_module": {
                "resources": list(resources),
                "child_modules": [],
            }
        },
        "sensitive_values": {},
    }


def _state_resource(address, resource_type, *, value="provider-private-value"):
    return {
        "address": address,
        "mode": "managed",
        "type": resource_type,
        "name": address.rsplit(".", 1)[-1],
        "values": {"id": value, "region": "test-region"},
    }


def _published_topology(env, *, scope_id="lab-1"):
    profile = env["topology"].create_profile(
        project_id="project-1", name="Lab topology",
        scope_type="LAB", scope_id=scope_id, actor="topology-admin",
    )
    revision = env["topology"].create_revision(
        profile["profile_id"],
        definition={
            "nodes": [
                {"id": "router-1", "name": "Edge Router", "node_type": "ROUTER", "x": 10, "y": 20},
                {"id": "switch-1", "name": "Access Switch", "node_type": "SWITCH", "x": 30, "y": 40},
            ],
            "links": [],
        },
        actor="topology-admin",
    )
    return profile, env["topology"].publish(
        profile["profile_id"], revision["revision_id"], actor="topology-admin",
    )


def _bind(env, *, address, node="router-1", profile=None, revision=None):
    if profile is None or revision is None:
        profile, revision = _published_topology(env)
    return env["service"].create_resource_binding(
        env["workspace"]["workspace_id"],
        resource_address=address,
        topology_profile_id=profile["profile_id"],
        topology_revision_id=revision["revision_id"],
        topology_node_id=node,
        actor="infra-admin",
    )


def test_resource_binding_requires_actual_state_and_exact_published_topology_node(infrastructure_environment):
    env = infrastructure_environment
    env["runner"].state = _state(_state_resource("aws_instance.router", "aws_instance"))
    profile, revision = _published_topology(env)
    binding = _bind(env, address="aws_instance.router", profile=profile, revision=revision)
    assert binding["resource_address"] == "aws_instance.router"
    assert binding["topology_revision_id"] == revision["revision_id"]
    assert binding["topology_node_id"] == "router-1"

    with pytest.raises(InfrastructureAutomationConflict, match="not present"):
        env["service"].create_resource_binding(
            env["workspace"]["workspace_id"],
            resource_address="aws_vpc.not_in_state",
            topology_profile_id=profile["profile_id"],
            topology_revision_id=revision["revision_id"],
            topology_node_id="router-1", actor="infra-admin",
        )
    with pytest.raises(InfrastructureAutomationNotFound, match="logical topology node"):
        env["service"].create_resource_binding(
            env["workspace"]["workspace_id"],
            resource_address="aws_instance.router",
            topology_profile_id=profile["profile_id"],
            topology_revision_id=revision["revision_id"],
            topology_node_id="node-not-in-revision", actor="infra-admin",
        )
    with pytest.raises(InfrastructureAutomationConflict, match="different active topology mapping"):
        env["service"].create_resource_binding(
            env["workspace"]["workspace_id"],
            resource_address="aws_instance.router",
            topology_profile_id=profile["profile_id"],
            topology_revision_id=revision["revision_id"],
            topology_node_id="switch-1", actor="infra-admin",
        )
    rebound = env["service"].create_resource_binding(
        env["workspace"]["workspace_id"],
        resource_address="aws_instance.router",
        topology_profile_id=profile["profile_id"],
        topology_revision_id=revision["revision_id"],
        topology_node_id="switch-1", actor="infra-admin",
        expected_current_binding_id=binding["binding_id"],
    )
    assert rebound["status"] == "ACTIVE"
    assert rebound["binding_id"] != binding["binding_id"]
    assert rebound["topology_node_id"] == "switch-1"
    history = env["service"].list_resource_bindings(env["workspace"]["workspace_id"])["items"]
    old = next(item for item in history if item["binding_id"] == binding["binding_id"])
    assert old["status"] == "SUPERSEDED"
    assert old["superseded_by"] == rebound["binding_id"]
    assert old["observed_status"] == "HISTORICAL"
    with pytest.raises(InfrastructureAutomationConflict, match="different active topology mapping"):
        env["service"].create_resource_binding(
            env["workspace"]["workspace_id"],
            resource_address="aws_instance.router",
            topology_profile_id=profile["profile_id"],
            topology_revision_id=revision["revision_id"],
            topology_node_id="router-1", actor="infra-admin",
            expected_current_binding_id=binding["binding_id"],
        )
    with pytest.raises(sqlite3.IntegrityError, match="bindings are immutable"):
        with env["database"].transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE infrastructure_resource_bindings SET topology_node_id='switch-1' WHERE binding_id=?",
                (binding["binding_id"],),
            )
    reconciled = env["service"].reconcile(env["workspace"]["workspace_id"], actor="observer")
    assert reconciled["orphan_count"] == 0
    assert reconciled["missing_count"] == 0
    active = next(item for item in reconciled["details"]["resources"] if item["resource_address"] == "aws_instance.router")
    assert active["binding_id"] == rebound["binding_id"]
    assert active["topology_node_id"] == "switch-1"


def test_resource_binding_rejects_draft_or_wrong_lab_topology(infrastructure_environment):
    env = infrastructure_environment
    env["runner"].state = _state(_state_resource("aws_instance.router", "aws_instance"))
    profile, revision = _published_topology(env)

    draft = env["topology"].create_revision(
        profile["profile_id"],
        definition={"nodes": [{"id": "router-1", "name": "Edge Router", "node_type": "ROUTER", "x": 1, "y": 1}], "links": []},
        actor="topology-admin",
    )
    with pytest.raises(InfrastructureAutomationConflict, match="published immutable revision"):
        env["service"].create_resource_binding(
            env["workspace"]["workspace_id"], resource_address="aws_instance.router",
            topology_profile_id=profile["profile_id"], topology_revision_id=draft["revision_id"],
            topology_node_id="router-1", actor="infra-admin",
        )

    with env["database"].transaction(immediate=True) as connection:
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-2", "project-1", "Other Lab", "gns3", 1, "ACTIVE", now, now),
        )
    other_profile, other_revision = _published_topology(env, scope_id="lab-2")
    with pytest.raises(InfrastructureAutomationConflict, match="different Lab"):
        env["service"].create_resource_binding(
            env["workspace"]["workspace_id"], resource_address="aws_instance.router",
            topology_profile_id=other_profile["profile_id"],
            topology_revision_id=other_revision["revision_id"],
            topology_node_id="router-1", actor="infra-admin",
        )


def test_reconciliation_detects_drift_orphans_and_missing_mappings_without_state_values(infrastructure_environment):
    env = infrastructure_environment
    env["runner"].state = _state(
        _state_resource("aws_instance.router", "aws_instance", value="do-not-return-this-secret"),
        _state_resource("aws_subnet.missing", "aws_subnet"),
        _state_resource("aws_vpc.orphan", "aws_vpc"),
    )
    profile, revision = _published_topology(env)
    _bind(env, address="aws_instance.router", node="router-1", profile=profile, revision=revision)
    _bind(env, address="aws_subnet.missing", node="switch-1", profile=profile, revision=revision)

    # Simulate the provider state after the remote subnet disappeared, while
    # the saved state still records the router and an unmanaged VPC.
    env["runner"].state = _state(
        _state_resource("aws_instance.router", "aws_instance", value="do-not-return-this-secret"),
        _state_resource("aws_vpc.orphan", "aws_vpc"),
    )
    env["runner"].drift = [{
        "address": "aws_instance.router",
        "type": "aws_instance",
        "change": {"actions": ["update"]},
    }]
    result = env["service"].reconcile(env["workspace"]["workspace_id"], actor="observer")

    assert result["status"] == "DRIFT_ORPHAN_OR_MISSING"
    assert result["resource_count"] == 2
    assert result["drift_count"] == 1
    assert result["orphan_count"] == 1
    assert result["missing_count"] == 1
    observations = {item["resource_address"]: item for item in result["details"]["resources"]}
    assert observations["aws_instance.router"]["status"] == "DRIFTED"
    assert observations["aws_vpc.orphan"]["status"] == "ORPHANED"
    assert observations["aws_subnet.missing"]["status"] == "MISSING"
    assert result["state_sha256"] == hashlib.sha256(
        json.dumps(env["runner"].state, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    assert "do-not-return-this-secret" not in json.dumps(result)
    assert env["runner"].plan_calls[-1]["refresh_only"] is True
    with pytest.raises(sqlite3.IntegrityError, match="reconciliation evidence is immutable"):
        with env["database"].transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE infrastructure_reconciliations SET status='CLEAN' WHERE reconciliation_id=?",
                (result["reconciliation_id"],),
            )
    listed = env["service"].list_resource_bindings(env["workspace"]["workspace_id"])
    assert {item["resource_address"]: item["observed_status"] for item in listed["items"]} == {
        "aws_instance.router": "DRIFTED",
        "aws_subnet.missing": "MISSING",
    }


def test_recovery_is_refresh_first_plan_based_and_requires_independent_approval(infrastructure_environment):
    env = infrastructure_environment
    service = env["service"]
    runner = env["runner"]

    failed_plan = service.create_plan(env["workspace"]["workspace_id"], actor="creator")
    service.approve(
        failed_plan["plan_id"], expected_plan_sha256=failed_plan["plan_sha256"],
        confirmed=True, actor="reviewer",
    )
    runner.apply_success = False
    failed = service.apply(
        failed_plan["plan_id"], expected_plan_sha256=failed_plan["plan_sha256"],
        confirmed=True, actor="operator",
    )
    assert failed["status"] == "FAILED"
    assert service.get_workspace(env["workspace"]["workspace_id"])["status"] == "RECOVERY_REQUIRED"

    runner.state = _state(_state_resource("aws_instance.router", "aws_instance", value="after-partial-apply"))
    reconciliation = service.reconcile(env["workspace"]["workspace_id"], actor="recovery-operator")
    recovery = service.create_recovery_plan(
        env["workspace"]["workspace_id"],
        reconciliation_id=reconciliation["reconciliation_id"],
        actor="recovery-operator",
    )
    assert recovery["kind"] == "RECOVERY"
    assert recovery["reconciliation_id"] == reconciliation["reconciliation_id"]
    with pytest.raises(InfrastructureAutomationConflict, match="cannot approve their own"):
        service.approve(
            recovery["plan_id"], expected_plan_sha256=recovery["plan_sha256"],
            confirmed=True, actor="recovery-operator",
        )
    service.approve(
        recovery["plan_id"], expected_plan_sha256=recovery["plan_sha256"],
        confirmed=True, actor="independent-reviewer",
    )
    runner.apply_success = True
    recovered = service.apply(
        recovery["plan_id"], expected_plan_sha256=recovery["plan_sha256"],
        confirmed=True, actor="recovery-executor",
    )
    assert recovered["status"] == "APPLIED"
    assert recovered["kind"] == "RECOVERY"
    assert service.get_workspace(env["workspace"]["workspace_id"])["status"] == "ACTIVE"


def test_newer_reconciliation_invalidates_an_unapplied_recovery_plan(infrastructure_environment):
    env = infrastructure_environment
    service = env["service"]
    runner = env["runner"]
    plan = service.create_plan(env["workspace"]["workspace_id"], actor="creator")
    service.approve(plan["plan_id"], expected_plan_sha256=plan["plan_sha256"], confirmed=True, actor="reviewer")
    runner.apply_success = False
    service.apply(plan["plan_id"], expected_plan_sha256=plan["plan_sha256"], confirmed=True, actor="operator")

    first = service.reconcile(env["workspace"]["workspace_id"], actor="operator")
    recovery = service.create_recovery_plan(
        env["workspace"]["workspace_id"], reconciliation_id=first["reconciliation_id"], actor="operator",
    )
    service.approve(recovery["plan_id"], expected_plan_sha256=recovery["plan_sha256"], confirmed=True, actor="reviewer")
    service.reconcile(env["workspace"]["workspace_id"], actor="observer")
    runner.apply_success = True
    with pytest.raises(InfrastructureAutomationConflict, match="newer reconciliation"):
        service.apply(
            recovery["plan_id"], expected_plan_sha256=recovery["plan_sha256"],
            confirmed=True, actor="operator",
        )


def test_reconciliation_distinguishes_orphan_and_missing_without_provider_drift(infrastructure_environment):
    env = infrastructure_environment
    env["runner"].state = _state(_state_resource("aws_instance.managed", "aws_instance"))
    profile, revision = _published_topology(env)
    _bind(env, address="aws_instance.managed", node="router-1", profile=profile, revision=revision)
    env["runner"].state = _state(_state_resource("aws_vpc.unmapped", "aws_vpc"))
    env["runner"].drift = []
    result = env["service"].reconcile(env["workspace"]["workspace_id"], actor="observer")
    assert result["status"] == "ORPHANED_AND_MISSING"
    assert result["drift_count"] == 0
    assert result["orphan_count"] == 1
    assert result["missing_count"] == 1
