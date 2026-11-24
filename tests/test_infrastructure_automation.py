from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from lib.repositories import SQLiteDatabase
from lib.services.infrastructure_automation import (
    InfrastructureAutomationConflict,
    InfrastructureAutomationError,
    InfrastructureAutomationService,
)
from lib.services.resource_lock import ResourceLockManager


class FakeOpenTofuRunner:
    def __init__(self, *, apply_success=True):
        self.apply_success = apply_success
        self.apply_calls = 0

    def prepare(self, *, workspace):
        return {"valid": True, "version": "OpenTofu v1.9.0"}

    def plan(self, *, workspace, plan_file, destroy=False, refresh_only=False):
        target = workspace / plan_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture-binary-plan-" + (b"destroy" if destroy else b"apply"))
        return {
            "valid": True,
            "has_changes": True,
            "plan_json": {
                "resource_changes": [{
                    "address": "null_resource.fixture",
                    "type": "null_resource",
                    "change": {"actions": ["delete", "create"] if destroy else ["create"]},
                }],
                "output_changes": {"endpoint": {"actions": ["create"], "after_sensitive": False}},
            },
        }

    def apply(self, *, workspace, plan_file):
        self.apply_calls += 1
        return {"success": self.apply_success, "exit_code": 0 if self.apply_success else 1, "timed_out": False}

    def state_list(self, *, workspace):
        return ["null_resource.fixture"] if self.apply_success else []


@pytest.fixture
def infrastructure_lab(tmp_path):
    database = SQLiteDatabase(tmp_path / "infrastructure.sqlite")
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
    modules = tmp_path / "modules"
    module = modules / "local-fixture"
    module.mkdir(parents=True)
    (module / "main.tf").write_text('terraform { required_version = ">= 1.8.0" }\n', encoding="utf-8")
    runner = FakeOpenTofuRunner()
    service = InfrastructureAutomationService(
        database, runner=runner, module_root=modules,
        state_root=tmp_path / "private-state",
        resource_lock_manager=ResourceLockManager(tmp_path / "shared-locks"),
    )
    return {"database": database, "runner": runner, "service": service, "modules": modules, "module": module}


def _workspace(lab, *, actor="creator"):
    return lab["service"].create_workspace(
        project_id="project-1", lab_id="lab-1", name="Primary infrastructure",
        module_key="local-fixture", variables={"region": "fixture-region", "count": 1}, actor=actor,
    )


def _plan(lab, *, kind="APPLY"):
    workspace = _workspace(lab)
    plan = lab["service"].create_plan(workspace["workspace_id"], kind=kind, actor="creator")
    return workspace, plan


def test_workspace_is_project_lab_scoped_and_module_snapshot_is_private(infrastructure_lab):
    service = infrastructure_lab["service"]
    workspace = _workspace(infrastructure_lab)
    path = service._workspace_path(workspace["workspace_id"])
    assert workspace["project_id"] == "project-1"
    assert workspace["lab_id"] == "lab-1"
    assert workspace["module_sha256"]
    assert (path / "main.tf").is_file()
    assert (path / "terraform.tfvars.json").read_text(encoding="utf-8") == '{"count":1,"region":"fixture-region"}'
    assert os.stat(path).st_mode & 0o777 == 0o700
    assert os.stat(path / "terraform.tfvars.json").st_mode & 0o777 == 0o600
    assert "region" not in json.dumps(workspace)


def test_secret_variables_and_module_symlinks_are_rejected(infrastructure_lab, tmp_path):
    service = infrastructure_lab["service"]
    with pytest.raises(InfrastructureAutomationError, match="secret values"):
        service._validate_variables({"client_secret": "not-accepted"})
    outside = tmp_path / "outside.tf"
    outside.write_text("terraform {}\n", encoding="utf-8")
    (infrastructure_lab["module"] / "escape.tf").symlink_to(outside)
    with pytest.raises(InfrastructureAutomationError, match="symlinks"):
        service.create_workspace(
            project_id="project-1", lab_id="lab-1", name="Unsafe workspace",
            module_key="local-fixture", variables={}, actor="creator",
        )


def test_plan_requires_independent_hash_pinned_approval_before_apply(infrastructure_lab):
    service = infrastructure_lab["service"]
    workspace, plan = _plan(infrastructure_lab)
    assert plan["status"] == "PREVIEWED"
    assert plan["summary"]["resource_change_count"] == 1
    assert plan["summary"]["resources"][0]["actions"] == ["create"]
    assert plan["plan_sha256"]
    with pytest.raises(InfrastructureAutomationConflict, match="cannot approve their own"):
        service.approve(plan["plan_id"], expected_plan_sha256=plan["plan_sha256"], confirmed=True, actor="creator")
    approved = service.approve(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"], confirmed=True, actor="reviewer",
    )
    assert approved["status"] == "APPROVED"
    applied = service.apply(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"], confirmed=True, actor="operator",
    )
    assert applied["status"] == "APPLIED"
    assert service.get_workspace(workspace["workspace_id"])["status"] == "ACTIVE"
    assert infrastructure_lab["runner"].apply_calls == 1


def test_plan_file_tampering_blocks_review(infrastructure_lab):
    service = infrastructure_lab["service"]
    _, plan = _plan(infrastructure_lab)
    path = service._workspace_path(plan["workspace_id"]) / ".netregress" / "plans" / f"{plan['plan_id']}.tfplan"
    path.write_bytes(b"tampered-plan")
    with pytest.raises(InfrastructureAutomationConflict, match="SHA-256"):
        service.get_plan(plan["plan_id"])


def test_failed_apply_marks_workspace_recovery_required_without_retry(infrastructure_lab):
    service = infrastructure_lab["service"]
    infrastructure_lab["runner"].apply_success = False
    workspace, plan = _plan(infrastructure_lab)
    service.approve(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"], confirmed=True, actor="reviewer",
    )
    result = service.apply(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"], confirmed=True, actor="operator",
    )
    assert result["status"] == "FAILED"
    assert result["executions"][0]["result"]["recovery_required"] is True
    assert service.get_workspace(workspace["workspace_id"])["status"] == "RECOVERY_REQUIRED"
    assert infrastructure_lab["runner"].apply_calls == 1
    with pytest.raises(InfrastructureAutomationConflict, match="recovery planning"):
        service.create_plan(workspace["workspace_id"], actor="creator")


def test_destroy_plan_requires_explicit_destroy_authorization(infrastructure_lab):
    service = infrastructure_lab["service"]
    workspace, plan = _plan(infrastructure_lab, kind="DESTROY")
    service.approve(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"], confirmed=True, actor="reviewer",
    )
    with pytest.raises(InfrastructureAutomationConflict, match="destroy-level authorization"):
        service.apply(
            plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
            confirmed=True, actor="operator",
        )
    result = service.apply(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
        confirmed=True, actor="operator", destroy_authorized=True,
    )
    assert result["status"] == "APPLIED"
    assert service.get_workspace(workspace["workspace_id"])["status"] == "DESTROYED"


def test_workspace_module_and_variable_snapshot_tampering_blocks_planning(infrastructure_lab):
    service = infrastructure_lab["service"]
    workspace = _workspace(infrastructure_lab)
    path = service._workspace_path(workspace["workspace_id"])
    (path / "main.tf").write_text('terraform { required_version = ">= 1.9.0" }\n', encoding="utf-8")
    with pytest.raises(InfrastructureAutomationConflict, match="module snapshot file failed SHA-256"):
        service.create_plan(workspace["workspace_id"], actor="creator")
    (path / "main.tf").write_text('terraform { required_version = ">= 1.8.0" }\n', encoding="utf-8")
    (path / "terraform.tfvars.json").write_text('{"region":"tampered"}', encoding="utf-8")
    with pytest.raises(InfrastructureAutomationConflict, match="variable snapshot failed integrity"):
        service.create_plan(workspace["workspace_id"], actor="creator")


def test_plan_summary_scans_all_changes_for_destroy_permission_even_when_display_is_bounded():
    changes = [
        {
            "address": f"null_resource.fixture_{index}",
            "type": "null_resource",
            "change": {"actions": ["create"]},
        }
        for index in range(2001)
    ]
    changes[-1]["change"]["actions"] = ["delete", "create"]
    summary = InfrastructureAutomationService._plan_summary(
        {"resource_changes": changes, "output_changes": {}},
        kind="APPLY",
    )
    assert summary["resource_change_count"] == 2001
    assert summary["resource_list_truncated"] is True
    assert len(summary["resources"]) == 2000
    assert summary["requires_destroy_permission"] is True


def test_workspace_snapshot_rejects_unmanifested_configuration_and_manifest_tampering(infrastructure_lab):
    service = infrastructure_lab["service"]
    workspace = _workspace(infrastructure_lab)
    path = service._workspace_path(workspace["workspace_id"])

    # OpenTofu auto-loads extra .tf files, so configuration not present in the
    # immutable module manifest must fail closed before the runner is invoked.
    unmanifested = path / "injected.tf"
    unmanifested.write_text('terraform { required_version = ">= 1.0.0" }\n', encoding="utf-8")
    with pytest.raises(InfrastructureAutomationConflict, match="unmanifested or missing files"):
        service.create_plan(workspace["workspace_id"], actor="creator")
    unmanifested.unlink()

    manifest_path = path / ".netregress" / "module-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["module_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(InfrastructureAutomationConflict, match="manifest does not match"):
        service.create_plan(workspace["workspace_id"], actor="creator")
    with pytest.raises(InfrastructureAutomationConflict, match="manifest does not match"):
        service.inspect(workspace["workspace_id"])
