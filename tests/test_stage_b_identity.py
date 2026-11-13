from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dashboard.app import create_app
from lib.domain.resources import Organization, Project, ProjectMembership, new_resource_id
from lib.repositories import (
    SQLiteDatabase,
    SQLiteOrganizationRepository,
    SQLiteProjectMembershipRepository,
    SQLiteProjectRepository,
)
from lib.security import AuthManager, Role, UserRecord
from lib.services.identity import IdentityPolicyError, IdentityStore


PASSWORD = "correct-horse-battery-staple-2026"


def _new_store(tmp_path):
    database = SQLiteDatabase(tmp_path / "identity.sqlite")
    database.initialize()
    return database, IdentityStore(database)


def _create_project(database):
    now = datetime.now(timezone.utc)
    organization = Organization(new_resource_id(), "identity-org", "Identity Org", now, now)
    project = Project(
        new_resource_id(), organization.organization_id,
        "identity-project", "Identity Project", now, now,
    )
    SQLiteOrganizationRepository(database).save(organization)
    SQLiteProjectRepository(database).save(project)
    return project


def test_bootstrap_user_is_persisted_and_global_role_is_authoritative(tmp_path):
    database, identity = _new_store(tmp_path)
    identity.ensure_bootstrap_user(
        "owner", AuthManager.password_hash(PASSWORD), "OWNER"
    )

    user = identity.get_user("owner")
    assert user is not None
    assert user["status"] == "ACTIVE"
    assert identity.permission_codes("owner")
    assert identity.authorize("owner", "owner") is True
    assert identity.authorize("owner", "view") is True

    identity.ensure_bootstrap_user(
        "owner", AuthManager.password_hash("different-but-valid-password"), "VIEWER"
    )
    # A later environment/configuration change must not overwrite a persisted
    # role or credential record.
    assert identity.get_user("owner")["password_hash"] == user["password_hash"]
    assert "system.manage" in identity.permission_codes("owner")


def test_invitation_activation_is_one_time_and_sessions_are_revocable(tmp_path):
    _, identity = _new_store(tmp_path)
    identity.ensure_bootstrap_user(
        "owner", AuthManager.password_hash(PASSWORD), "OWNER"
    )
    invited, token = identity.invite_user(
        username="new-operator",
        email="new-operator@example.test",
        display_name="New Operator",
        global_role_id="global_operator",
        actor="owner",
    )
    assert invited["status"] == "INVITED"

    active = identity.accept_invitation(token, "another-secure-password")
    assert active["status"] == "ACTIVE"
    with pytest.raises(IdentityPolicyError, match="invalid, expired or already used"):
        identity.accept_invitation(token, "another-secure-password")

    session_id = identity.create_session("new-operator")
    assert identity.validate_session("new-operator", session_id)
    assert identity.revoke_sessions("new-operator") == 1
    assert not identity.validate_session("new-operator", session_id)


def test_password_reset_invalidates_existing_sessions_and_consumes_token(tmp_path):
    _, identity = _new_store(tmp_path)
    identity.ensure_bootstrap_user(
        "owner", AuthManager.password_hash(PASSWORD), "OWNER"
    )
    session_id = identity.create_session("owner")
    reset_token = identity.issue_password_reset("owner", "owner")

    identity.complete_password_reset(reset_token, "reset-password-2026!")
    assert not identity.validate_session("owner", session_id)
    with pytest.raises(IdentityPolicyError, match="invalid, expired or already used"):
        identity.complete_password_reset(reset_token, "reset-password-2026!")


def test_project_role_permissions_are_intersected_with_global_authority(tmp_path):
    database, identity = _new_store(tmp_path)
    identity.ensure_bootstrap_user(
        "operator", AuthManager.password_hash(PASSWORD), "OPERATOR"
    )
    identity.ensure_bootstrap_user(
        "viewer", AuthManager.password_hash(PASSWORD), "VIEWER"
    )
    project = _create_project(database)
    now = datetime.now(timezone.utc)
    memberships = SQLiteProjectMembershipRepository(database)
    memberships.save(ProjectMembership("operator", project.project_id, "OPERATOR", now, "owner"))
    memberships.save(ProjectMembership("viewer", project.project_id, "VIEWER", now, "owner"))

    assert identity.authorize("operator", "execute", project.project_id)
    assert not identity.authorize("viewer", "execute", project.project_id)

    custom = identity.create_role(
        name="Run executor", scope_type="PROJECT",
        description="Can run tests but cannot administer the workspace", actor="owner",
    )
    custom = identity.set_role_permissions(
        custom["role_id"], ["workspace.read", "runs.execute"], "owner"
    )
    identity.assign_project_role(
        username="viewer", role_id=custom["role_id"],
        scope_type="PROJECT", scope_id=project.project_id, actor="owner",
    )
    # A custom Project role cannot elevate a Global Viewer.
    assert not identity.authorize("viewer", "execute", project.project_id)
    assert identity.authorize("operator", "execute", project.project_id)


def test_last_active_global_owner_cannot_be_suspended_or_demoted(tmp_path):
    _, identity = _new_store(tmp_path)
    identity.ensure_bootstrap_user(
        "owner", AuthManager.password_hash(PASSWORD), "OWNER"
    )
    with pytest.raises(IdentityPolicyError, match="last active Global Owner"):
        identity.set_user_status("owner", "SUSPENDED", "owner")
    with pytest.raises(IdentityPolicyError, match="last active Global Owner"):
        identity.assign_role(
            username="owner", role_id="global_admin",
            scope_type="GLOBAL", scope_id="*", actor="owner",
        )


def test_global_owner_guard_allows_transition_when_another_owner_is_active(tmp_path):
    _, identity = _new_store(tmp_path)
    identity.ensure_bootstrap_user(
        "owner-one", AuthManager.password_hash(PASSWORD), "OWNER"
    )
    identity.ensure_bootstrap_user(
        "owner-two", AuthManager.password_hash(PASSWORD), "OWNER"
    )
    identity.set_user_status("owner-one", "SUSPENDED", "owner-two")
    assert identity.get_user("owner-one")["status"] == "SUSPENDED"
    with pytest.raises(IdentityPolicyError, match="last active Global Owner"):
        identity.set_user_status("owner-two", "DEACTIVATED", "owner-two")


def test_audit_records_capture_identity_and_role_changes(tmp_path):
    _, identity = _new_store(tmp_path)
    identity.ensure_bootstrap_user(
        "owner", AuthManager.password_hash(PASSWORD), "OWNER"
    )
    identity.create_role(
        name="Audit Reader", scope_type="GLOBAL",
        description="Can view audit events", actor="owner",
    )
    events = identity.list_audit(limit=20)
    actions = {item["action"] for item in events}
    assert "ACCOUNT_BOOTSTRAPPED" in actions
    assert "ROLE_CREATED" in actions


def _owner_client(tmp_path):
    manager = AuthManager(
        (UserRecord("owner", AuthManager.password_hash(PASSWORD), Role.OWNER, ("*",)),),
        required=True,
    )
    app = create_app(tmp_path / "workspace-api.sqlite", auth_manager=manager)
    app.config.update(TESTING=True)
    client = app.test_client()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": PASSWORD},
    )
    assert login.status_code == 200
    return app, client, login.get_json()["data"]["csrf_token"]


def test_workspace_membership_scope_is_live_and_session_revocation_is_immediate(tmp_path):
    app, owner, owner_csrf = _owner_client(tmp_path)
    invited = owner.post(
        "/api/v1/identity/invitations",
        headers={"X-CSRF-Token": owner_csrf},
        json={
            "username": "scoped-viewer",
            "email": "scoped-viewer@example.test",
            "display_name": "Scoped Viewer",
            "global_role_id": "global_viewer",
        },
    )
    assert invited.status_code == 201
    invitation_token = invited.get_json()["data"]["invitation_token"]

    activation = app.test_client().post(
        "/api/v1/auth/invitations/accept",
        json={"token": invitation_token, "password": "viewer-password-2026!"},
    )
    assert activation.status_code == 200

    now = datetime.now(timezone.utc)
    org_response = owner.post(
        "/api/v1/workspace/organizations",
        headers={"X-CSRF-Token": owner_csrf},
        json={"slug": "network-ops", "name": "Network Operations"},
    )
    assert org_response.status_code == 201
    organization_id = org_response.get_json()["data"]["organization_id"]
    project_response = owner.post(
        "/api/v1/workspace/projects",
        headers={"X-CSRF-Token": owner_csrf},
        json={"organization_id": organization_id, "slug": "wireless", "name": "Wireless"},
    )
    assert project_response.status_code == 201
    project_id = project_response.get_json()["data"]["project_id"]

    viewer = app.test_client()
    login = viewer.post(
        "/api/v1/auth/login",
        json={"username": "scoped-viewer", "password": "viewer-password-2026!"},
    )
    assert login.status_code == 200
    assert viewer.get("/api/v1/runs").status_code == 403

    added = owner.post(
        f"/api/v1/workspace/projects/{project_id}/members",
        headers={"X-CSRF-Token": owner_csrf},
        json={"username": "scoped-viewer", "role": "VIEWER"},
    )
    assert added.status_code == 201
    assert viewer.get(f"/api/v1/workspace/projects/{project_id}").status_code == 200
    assert viewer.get("/api/v1/runs").status_code == 200

    revoked = owner.delete(
        f"/api/v1/workspace/projects/{project_id}/members/scoped-viewer",
        headers={"X-CSRF-Token": owner_csrf},
    )
    assert revoked.status_code == 200
    assert viewer.get(f"/api/v1/workspace/projects/{project_id}").status_code == 403
    assert viewer.get("/api/v1/runs").status_code == 403

    session_revoke = owner.post(
        "/api/v1/identity/users/scoped-viewer/sessions/revoke",
        headers={"X-CSRF-Token": owner_csrf},
    )
    assert session_revoke.status_code == 200
    assert viewer.get("/api/v1/auth/me").status_code == 401


def test_audit_events_are_append_only_at_the_sqlite_boundary(tmp_path):
    database, identity = _new_store(tmp_path)
    identity.ensure_bootstrap_user(
        "owner", AuthManager.password_hash(PASSWORD), "OWNER"
    )
    event = identity.list_audit(limit=1)[0]
    with pytest.raises(Exception, match="audit events are immutable"):
        with database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE audit_events SET action='TAMPERED' WHERE audit_id=?",
                (event["audit_id"],),
            )
    with pytest.raises(Exception, match="audit events are immutable"):
        with database.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM audit_events WHERE audit_id=?",
                (event["audit_id"],),
            )


def test_last_project_owner_cannot_be_demoted_or_removed(tmp_path):
    database, identity = _new_store(tmp_path)
    identity.ensure_bootstrap_user(
        "owner", AuthManager.password_hash(PASSWORD), "OWNER"
    )
    identity.ensure_bootstrap_user(
        "viewer", AuthManager.password_hash(PASSWORD), "VIEWER"
    )
    project = _create_project(database)
    now = datetime.now(timezone.utc)
    memberships = SQLiteProjectMembershipRepository(database)
    memberships.save(ProjectMembership("owner", project.project_id, "OWNER", now, "owner"))
    memberships.save(ProjectMembership("viewer", project.project_id, "VIEWER", now, "owner"))
    with pytest.raises(IdentityPolicyError, match="last Project Owner"):
        identity.demote_project_owner(
            username="owner", project_id=project.project_id,
            new_role_id="project_viewer", actor="owner",
        )
