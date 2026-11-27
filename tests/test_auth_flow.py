from dashboard.app import create_app
from lib.repositories import SQLiteDatabase
from lib.security import AuthManager, Role, UserRecord
from lib.services.identity import IdentityStore


PASSWORD = "correct-horse-battery-staple-2026"


def make_authenticated_client(tmp_path):
    manager = AuthManager(
        (UserRecord("owner", AuthManager.password_hash(PASSWORD), Role.OWNER, ("*",)),),
        required=True,
    )
    app = create_app(tmp_path / "auth.sqlite", auth_manager=manager)
    app.config.update(TESTING=True)
    return app.test_client()


def test_owner_login_session_csrf_and_logout(tmp_path):
    client = make_authenticated_client(tmp_path)

    unauthenticated = client.get("/api/v1/auth/me")
    assert unauthenticated.status_code == 401
    assert unauthenticated.get_json()["error"]["code"] == "UNAUTHENTICATED"

    invalid = client.post("/api/v1/auth/login", json={"username": "owner", "password": "wrong-password"})
    assert invalid.status_code == 401
    assert invalid.get_json()["error"]["code"] == "INVALID_CREDENTIALS"

    login = client.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD})
    assert login.status_code == 200
    payload = login.get_json()["data"]
    assert payload["username"] == "owner"
    assert payload["role"] == "OWNER"
    assert payload["csrf_token"]

    current_user = client.get("/api/v1/auth/me")
    assert current_user.status_code == 200
    assert current_user.get_json()["data"]["username"] == "owner"

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": payload["csrf_token"]},
    )
    assert logout.status_code == 200
    assert logout.get_json()["data"]["logged_out"] is True
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_explains_missing_auth_configuration(tmp_path):
    app = create_app(tmp_path / "auth.sqlite", auth_manager=AuthManager((), required=True))
    app.config.update(TESTING=True)
    response = app.test_client().post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": PASSWORD},
    )
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "AUTH_NOT_CONFIGURED"


def test_first_run_owner_setup_can_login_and_open_workspace_api(tmp_path):
    app = create_app(
        tmp_path / "first-run.sqlite",
        auth_manager=AuthManager((), required=True),
    )
    app.config.update(TESTING=True)
    client = app.test_client()

    setup_status = client.get("/api/v1/setup/status")
    assert setup_status.status_code == 200
    assert setup_status.get_json()["data"]["first_run_required"] is True

    created = client.post(
        "/api/v1/setup/owner",
        json={"username": "owner", "password": PASSWORD},
    )
    assert created.status_code == 200
    assert created.get_json()["data"]["global_role"] == "OWNER"

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": PASSWORD},
    )
    assert login.status_code == 200
    profile = login.get_json()["data"]
    assert profile["username"] == "owner"
    assert profile["role"] == "OWNER"
    assert "system.manage" in profile["permissions"]

    restored = client.get("/api/v1/auth/me")
    assert restored.status_code == 200, restored.get_json()
    assert restored.get_json()["data"]["username"] == "owner"

    # This is the first protected data request made after the login page closes.
    organizations = client.get("/api/v1/workspace/organizations")
    assert organizations.status_code == 200, organizations.get_json()

    projects = client.get("/api/v1/workspace/projects")
    assert projects.status_code == 200, projects.get_json()


def test_legacy_configured_accounts_are_imported_once_into_identity_store(tmp_path):
    manager = AuthManager(
        (UserRecord("legacy-owner", AuthManager.password_hash(PASSWORD), Role.OWNER, ("*",)),),
        required=True,
    )
    database_path = tmp_path / "legacy-auth.sqlite"
    app = create_app(database_path, auth_manager=manager)
    app.config.update(TESTING=True)
    client = app.test_client()

    assert manager.configured_users == ()
    identity = IdentityStore(SQLiteDatabase(database_path))
    persisted = identity.get_user("legacy-owner")
    assert persisted is not None
    assert persisted["workspace_scope"] == "WILDCARD"

    setup = client.get("/api/v1/setup/status")
    assert setup.status_code == 200
    assert setup.get_json()["data"]["first_run_required"] is False

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "legacy-owner", "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.get_json()["data"]["role"] == "OWNER"
    restored = client.get("/api/v1/auth/me")
    assert restored.status_code == 200
    assert restored.get_json()["data"]["username"] == "legacy-owner"
    assert client.get("/api/v1/workspace/organizations").status_code == 200


def test_persisted_identity_password_wins_over_stale_legacy_configuration(tmp_path):
    database_path = tmp_path / "database-authority.sqlite"
    database = SQLiteDatabase(database_path)
    database.initialize()
    identity = IdentityStore(database)
    identity.bootstrap_first_owner(
        "owner", AuthManager.password_hash("persisted-database-password-2026"), actor="test",
    )

    stale = AuthManager(
        (UserRecord("owner", AuthManager.password_hash("stale-legacy-password-2026"), Role.OWNER, ("*",)),),
        required=True,
    )
    app = create_app(database_path, auth_manager=stale)
    app.config.update(TESTING=True)
    client = app.test_client()

    assert stale.configured_users == ()
    old_password = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": "stale-legacy-password-2026"},
    )
    assert old_password.status_code == 401
    current_password = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": "persisted-database-password-2026"},
    )
    assert current_password.status_code == 200
    assert client.get("/api/v1/workspace/organizations").status_code == 200


def test_owner_password_reset_updates_database_and_revokes_sessions(tmp_path):
    database = SQLiteDatabase(tmp_path / "owner-reset.sqlite")
    database.initialize()
    identity = IdentityStore(database)
    identity.bootstrap_first_owner(
        "owner", AuthManager.password_hash(PASSWORD), actor="test",
    )
    session_id = identity.create_session("owner")

    result = identity.reset_owner_password(
        "owner", "new-persistent-owner-password-2026", actor="local-console-reset",
    )

    assert result["revoked_sessions"] == 1
    assert identity.validate_session("owner", session_id) is False
    new_credentials = AuthManager(
        (UserRecord("owner", identity.get_user("owner")["password_hash"], Role.OWNER, ("*",)),),
        required=True,
    )
    assert new_credentials.authenticate("owner", "new-persistent-owner-password-2026") is not None
    assert new_credentials.authenticate("owner", PASSWORD) is None
    assert any(
        item["action"] == "OWNER_PASSWORD_RESET"
        for item in identity.list_audit(resource_type="USER")
    )



def test_legacy_project_scope_is_migrated_to_persisted_membership(tmp_path):
    from datetime import datetime, timezone

    database_path = tmp_path / "legacy-project-scope.sqlite"
    database = SQLiteDatabase(database_path)
    database.initialize()
    now = datetime.now(timezone.utc).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO organizations(
                organization_id,slug,name,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?)""",
            ("org-legacy", "legacy-org", "Legacy Organization", "ACTIVE", now, now),
        )
        connection.execute(
            """INSERT INTO projects(
                project_id,organization_id,slug,name,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?)""",
            ("project-legacy", "org-legacy", "legacy-project", "Legacy Project", "ACTIVE", now, now),
        )

    manager = AuthManager(
        (UserRecord("legacy-viewer", AuthManager.password_hash(PASSWORD), Role.VIEWER, ("project-legacy",)),),
        required=True,
    )
    app = create_app(database_path, auth_manager=manager)
    app.config.update(TESTING=True)
    client = app.test_client()

    identity = IdentityStore(database)
    assert manager.configured_users == ()
    assert identity.project_ids_for_user("legacy-viewer") == ("project-legacy",)
    with database.connection() as connection:
        membership = connection.execute(
            "SELECT role FROM project_memberships WHERE username=? AND project_id=?",
            ("legacy-viewer", "project-legacy"),
        ).fetchone()
    assert membership is not None and membership["role"] == "VIEWER"

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "legacy-viewer", "password": PASSWORD},
    )
    assert login.status_code == 200
    profile = login.get_json()["data"]
    assert profile["role"] == "VIEWER"
    assert profile["projects"] == ["project-legacy"]
    scoped_projects = client.get("/api/v1/workspace/projects?project_id=project-legacy")
    assert scoped_projects.status_code == 200, scoped_projects.get_json()


def test_tauri_desktop_bearer_session_works_without_cookies_and_is_revocable(tmp_path):
    manager = AuthManager(
        (UserRecord("owner", AuthManager.password_hash(PASSWORD), Role.OWNER, ("*",)),),
        required=True,
    )
    app = create_app(tmp_path / "desktop-bearer.sqlite", auth_manager=manager)
    app.config.update(TESTING=True)

    login_client = app.test_client()
    login = login_client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": PASSWORD},
        headers={"Origin": "tauri://localhost"},
    )
    assert login.status_code == 200
    token = login.get_json()["data"]["session_id"]
    assert token
    assert "Set-Cookie" not in login.headers

    desktop = app.test_client()
    desktop_headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "tauri://localhost",
    }
    restored = desktop.get("/api/v1/auth/me", headers=desktop_headers)
    assert restored.status_code == 200, restored.get_json()
    assert restored.get_json()["data"]["username"] == "owner"
    assert "session_id" not in restored.get_json()["data"]
    assert "Set-Cookie" not in restored.headers

    first_workspace_request = desktop.get(
        "/api/v1/workspace/organizations",
        headers=desktop_headers,
    )
    assert first_workspace_request.status_code == 200, first_workspace_request.get_json()
    assert "Set-Cookie" not in first_workspace_request.headers

    # A route that creates a synchronizer token must still not serialize the
    # request-local bearer session into a Flask cookie.
    csrf_probe = desktop.get("/api/v1/auth/csrf", headers=desktop_headers)
    assert csrf_probe.status_code == 200, csrf_probe.get_json()
    assert "Set-Cookie" not in csrf_probe.headers

    # Explicit bearer authorization is the desktop CSRF boundary. Cookie-backed
    # browser mutations continue to require X-CSRF-Token.
    activity = desktop.post(
        "/api/v1/auth/activity",
        json={},
        headers={**desktop_headers, "Idempotency-Key": "desktop-activity-0001"},
    )
    assert activity.status_code == 200, activity.get_json()

    preflight = desktop.options(
        "/api/v1/auth/activity",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 200
    assert "authorization" in preflight.headers["Access-Control-Allow-Headers"].lower()

    untrusted_origin = app.test_client().get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://untrusted.example",
        },
    )
    assert untrusted_origin.status_code == 401

    non_loopback = app.test_client().get(
        "/api/v1/auth/me",
        headers=desktop_headers,
        environ_overrides={"REMOTE_ADDR": "192.0.2.20"},
    )
    assert non_loopback.status_code == 401

    logout = desktop.post("/api/v1/auth/logout", headers=desktop_headers)
    assert logout.status_code == 200, logout.get_json()
    assert "Set-Cookie" not in logout.headers
    revoked = app.test_client().get("/api/v1/auth/me", headers=desktop_headers)
    assert revoked.status_code == 401

