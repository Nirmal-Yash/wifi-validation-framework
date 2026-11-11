from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from lib.domain.resources import (
    Lab, Organization, Project, ResourceValidationError, new_resource_id,
)
from lib.repositories import (
    RepositoryConflictError,
    SQLiteDatabase,
    SQLiteLabRepository,
    SQLiteOrganizationRepository,
    SQLiteProjectRepository,
)


def _times():
    now = datetime.now(timezone.utc)
    return now, now + timedelta(seconds=1)


def _organization(slug="acme"):
    created, updated = _times()
    return Organization(new_resource_id(), slug, "Acme Networks", created, updated)


def _project(organization_id, slug="wifi"):
    created, updated = _times()
    return Project(new_resource_id(), organization_id, slug, "WiFi Validation", created, updated)


def _lab(project_id, name="reference-wifi"):
    created, updated = _times()
    return Lab(new_resource_id(), project_id, name, "gns3", created, updated)


def test_resource_identifiers_are_unique_and_uuid_based():
    first, second = new_resource_id(), new_resource_id()
    assert first != second
    assert len(first) == 36


def test_resource_domain_rejects_empty_ownership_and_invalid_version():
    created, updated = _times()
    with pytest.raises(ResourceValidationError, match="project_id"):
        Lab(new_resource_id(), "", "lab", "gns3", created, updated)
    with pytest.raises(ResourceValidationError, match="positive integer"):
        Lab(new_resource_id(), "project-1", "lab", "gns3", created, updated, topology_version=0)


def test_resource_repositories_persist_ownership_and_round_trip(tmp_path):
    database = SQLiteDatabase(tmp_path / "resources.sqlite")
    database.initialize()
    organizations = SQLiteOrganizationRepository(database)
    projects = SQLiteProjectRepository(database)
    labs = SQLiteLabRepository(database)

    organization = _organization()
    project = _project(organization.organization_id)
    lab = _lab(project.project_id)

    organizations.save(organization)
    projects.save(project)
    labs.save(lab)

    assert organizations.get(organization.organization_id) == organization
    assert organizations.get_by_slug("acme") == organization
    assert organizations.list() == [organization]
    assert projects.list_for_organization(organization.organization_id) == [project]
    assert labs.list_for_project(project.project_id) == [lab]

    changed_project = Project(
        project.project_id, project.organization_id, project.slug,
        "WiFi Lab Workspace", project.created_at, project.updated_at + timedelta(seconds=2),
    )
    projects.update(changed_project)
    assert projects.get(project.project_id) == changed_project

    changed_lab = Lab(
        lab.lab_id, lab.project_id, lab.name, "gns3-remote",
        lab.created_at, lab.updated_at + timedelta(seconds=2), topology_version=2,
    )
    labs.update(changed_lab)
    assert labs.get(lab.lab_id) == changed_lab


def test_resource_repositories_reject_duplicate_and_missing_parent(tmp_path):
    database = SQLiteDatabase(tmp_path / "resources.sqlite")
    database.initialize()
    organizations = SQLiteOrganizationRepository(database)
    projects = SQLiteProjectRepository(database)
    organization = _organization()
    organizations.save(organization)

    with pytest.raises(RepositoryConflictError):
        organizations.save(organization)
    with pytest.raises(RepositoryConflictError):
        organizations.save(_organization())  # different ID, duplicate organization slug

    project = _project(organization.organization_id)
    projects.save(project)
    duplicate_slug = _project(organization.organization_id)
    duplicate_slug = Project(
        duplicate_slug.project_id,
        duplicate_slug.organization_id,
        project.slug,
        "Duplicate",
        duplicate_slug.created_at,
        duplicate_slug.updated_at,
    )
    with pytest.raises(RepositoryConflictError):
        projects.save(duplicate_slug)

    with pytest.raises(RepositoryConflictError):
        projects.save(_project("missing-organization"))

    duplicate_lab = _lab(project.project_id)
    SQLiteLabRepository(database).save(duplicate_lab)
    with pytest.raises(RepositoryConflictError):
        SQLiteLabRepository(database).save(_lab(project.project_id))


def test_resource_update_requires_existing_resource(tmp_path):
    database = SQLiteDatabase(tmp_path / "resources.sqlite")
    database.initialize()
    organization = _organization()
    with pytest.raises(RepositoryConflictError, match="does not exist"):
        SQLiteOrganizationRepository(database).update(organization)
