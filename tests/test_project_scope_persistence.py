from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from lib.domain import (
    EnvironmentHealthStatus,
    Lab,
    Organization,
    Project,
    ProjectMembership,
    ResourceValidationError,
    new_resource_id,
)
from lib.repositories import (
    RepositoryConflictError,
    SQLiteDatabase,
    SQLiteLabRepository,
    SQLiteOrganizationRepository,
    SQLiteProjectMembershipRepository,
    SQLiteProjectRepository,
)
from lib.services import RunService


def _times():
    created = datetime.now(timezone.utc)
    return created, created + timedelta(seconds=1)


def _workspace(database, suffix=""):
    organizations = SQLiteOrganizationRepository(database)
    projects = SQLiteProjectRepository(database)
    labs = SQLiteLabRepository(database)
    created, updated = _times()
    organization = Organization(
        new_resource_id(), "network-team" + suffix, "Network Team" + suffix, created, updated
    )
    project = Project(
        new_resource_id(), organization.organization_id,
        "wifi-lab" + suffix, "WiFi Validation" + suffix, created, updated,
    )
    lab = Lab(
        new_resource_id(), project.project_id, "reference-lab" + suffix,
        "gns3", created, updated,
    )
    organizations.save(organization)
    projects.save(project)
    labs.save(lab)
    return organization, project, lab


def test_project_membership_persists_roles_and_supports_immediate_revocation(tmp_path):
    database = SQLiteDatabase(tmp_path / "scope.sqlite")
    database.initialize()
    _, project, _ = _workspace(database)
    repository = SQLiteProjectMembershipRepository(database)
    created, _ = _times()

    membership = ProjectMembership(
        username="operator",
        project_id=project.project_id,
        role="OPERATOR",
        created_at=created,
        created_by="owner",
    )
    repository.save(membership)

    assert repository.get("operator", project.project_id) == membership
    assert repository.list_for_user("operator") == [membership]
    assert repository.list_for_project(project.project_id) == [membership]
    assert repository.delete("operator", project.project_id) is True
    assert repository.get("operator", project.project_id) is None
    assert repository.delete("operator", project.project_id) is False


def test_project_membership_rejects_duplicate_missing_project_and_invalid_role(tmp_path):
    database = SQLiteDatabase(tmp_path / "membership-conflicts.sqlite")
    database.initialize()
    _, project, _ = _workspace(database)
    repository = SQLiteProjectMembershipRepository(database)
    created, _ = _times()
    member = ProjectMembership("viewer", project.project_id, "VIEWER", created, "owner")
    repository.save(member)

    with pytest.raises(RepositoryConflictError, match="already exists"):
        repository.save(member)
    with pytest.raises(RepositoryConflictError, match="does not exist"):
        repository.save(ProjectMembership(
            "viewer-2", "missing-project", "VIEWER", created, "owner"
        ))
    with pytest.raises(ResourceValidationError, match="role"):
        ProjectMembership("bad-role", project.project_id, "ROOT", created, "owner")


def test_run_project_owner_round_trips_and_retry_inherits_ownership(tmp_path):
    database = SQLiteDatabase(tmp_path / "run-owner.sqlite")
    database.initialize()
    _, project, lab = _workspace(database)
    service = RunService.from_sqlite(database)

    run, _ = service.create_run(
        firmware_version="v1.0",
        lab_id=lab.lab_id,
        validation_profile="Smoke",
        selected_tests=["wifi.latency.threshold"],
        test_definition_versions={"wifi.latency.threshold": "1.0"},
        resolved_config={},
        repository_commit="test-commit",
        project_id=project.project_id,
    )
    persisted = service.run_repository.get(run.run_id)
    assert persisted is not None
    assert persisted.project_id == project.project_id

    service.begin_lab_health_check(run.run_id)
    service.record_environment_health(run.run_id, EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(run.run_id)
    service.complete_run(run.run_id)

    retry, _ = service.create_run(
        firmware_version=run.firmware_version,
        lab_id=run.lab_id,
        validation_profile=run.validation_profile,
        selected_tests=list(run.selected_tests),
        test_definition_versions=dict(run.test_definition_versions),
        resolved_config=dict(run.resolved_config),
        repository_commit=run.repository_commit,
        source_run_id=run.run_id,
    )
    assert retry.project_id == project.project_id
    assert service.run_repository.get(retry.run_id).project_id == project.project_id


def test_run_cannot_reference_a_nonexistent_project(tmp_path):
    database = SQLiteDatabase(tmp_path / "missing-project.sqlite")
    database.initialize()
    service = RunService.from_sqlite(database)

    with pytest.raises(sqlite3.IntegrityError):
        service.create_run(
            firmware_version="v1.0",
            lab_id="legacy-lab",
            validation_profile="Smoke",
            selected_tests=["wifi.latency.threshold"],
            test_definition_versions={"wifi.latency.threshold": "1.0"},
            resolved_config={},
            repository_commit="test-commit",
            project_id="not-a-project",
        )



def test_run_must_reference_a_lab_in_the_same_project(tmp_path):
    database = SQLiteDatabase(tmp_path / "cross-project-lab.sqlite")
    database.initialize()
    _, project_a, _ = _workspace(database)
    _, project_b, lab_b = _workspace(database, "-secondary")
    service = RunService.from_sqlite(database)

    with pytest.raises(sqlite3.IntegrityError, match="lab must belong to its project"):
        service.create_run(
            firmware_version="v1.0",
            lab_id=lab_b.lab_id,
            validation_profile="Smoke",
            selected_tests=["wifi.latency.threshold"],
            test_definition_versions={"wifi.latency.threshold": "1.0"},
            resolved_config={},
            repository_commit="test-commit",
            project_id=project_a.project_id,
        )

    assert service.run_repository.list() == []
