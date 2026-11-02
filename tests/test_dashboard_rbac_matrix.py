from __future__ import annotations

import json
import time

from dashboard.app import create_app
from lib.security import AuthManager, AuthenticatedUser, Role, UserRecord


PASSWORD = "correct-horse-battery-staple-2026"


def _client(tmp_path, role: Role, username: str, projects=("*",)):
    manager = AuthManager(
        (UserRecord(username, AuthManager.password_hash(PASSWORD), role, tuple(projects)),),
        required=True,
    )
    app = create_app(tmp_path / f"{username}.sqlite", auth_manager=manager)
    app.config.update(TESTING=True)
    client = app.test_client()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200
    return app, client, login.get_json()["data"]["csrf_token"]


def test_named_session_cookie_is_http_only_same_site_and_sliding(tmp_path, monkeypatch):
    monkeypatch.setenv("NETREGRESS_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("NETREGRESS_SESSION_COOKIE_SECURE", "0")
    app, client, _ = _client(tmp_path, Role.OWNER, "owner")
    assert app.config["SESSION_COOKIE_NAME"] == "netregress_session"
    assert app.config["SESSION_COOKIE_PATH"] == "/"
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SESSION_REFRESH_EACH_REQUEST"] is True
    assert app.config["SESSION_IDLE_TIMEOUT_SECONDS"] == 1800
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": PASSWORD},
    )
    assert response.status_code == 200
    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith("netregress_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" not in cookie


def test_backend_role_permission_matrix():
    expected = {
        Role.OWNER: {"view": True, "execute": True, "admin": True, "owner": True},
        Role.ADMIN: {"view": True, "execute": True, "admin": True, "owner": False},
        Role.OPERATOR: {"view": True, "execute": True, "admin": False, "owner": False},
        Role.VIEWER: {"view": True, "execute": False, "admin": False, "owner": False},
    }
    for role, permissions in expected.items():
        actor = AuthenticatedUser("test-user", role, ("*",))
        for action, allowed in permissions.items():
            assert AuthManager.authorize(actor, action) is allowed


def test_project_scope_is_explicit_and_fails_closed():
    scoped = AuthenticatedUser("project-viewer", Role.VIEWER, ("project-a",))
    empty = AuthenticatedUser("empty-viewer", Role.VIEWER, ())
    wildcard = AuthenticatedUser("local-owner", Role.OWNER, ("*",))
    assert AuthManager.authorize(scoped, "view", "project-a") is True
    assert AuthManager.authorize(scoped, "view", "project-b") is False
    assert AuthManager.authorize(scoped, "view") is False
    assert AuthManager.authorize(empty, "view") is False
    assert AuthManager.authorize(wildcard, "view") is True


def test_operator_is_denied_admin_only_waiver_api(tmp_path):
    _, client, csrf = _client(tmp_path, Role.OPERATOR, "operator")
    response = client.post(
        "/api/v1/waivers",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "operator-waiver-denied"},
        json={
            "scope": "RELEASE",
            "target_id": "*",
            "issue_code": "TEST_ONLY",
            "reason": "This request must be rejected for an Operator.",
        },
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "FORBIDDEN"


def test_viewer_is_denied_run_execution_api(tmp_path):
    _, client, csrf = _client(tmp_path, Role.VIEWER, "viewer")
    response = client.post(
        "/api/v1/runs",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "viewer-run-denied"},
        json={"firmware_version": "v1.0", "tests": []},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "FORBIDDEN"


def test_empty_project_scope_does_not_default_to_wildcard(monkeypatch):
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("NETREGRESS_AUTH_USERS_JSON", json.dumps([{
        "username": "empty-scope",
        "password_hash": AuthManager.password_hash(PASSWORD),
        "role": "VIEWER",
        "projects": [],
    }]))
    manager = AuthManager.from_env()
    user = manager.authenticate("empty-scope", PASSWORD)
    assert user is not None
    assert user.projects == ()
    assert AuthManager.authorize(user, "view") is False


def test_project_scoped_user_fails_closed_on_unscoped_run_endpoint(tmp_path):
    _, client, _ = _client(
        tmp_path,
        Role.VIEWER,
        "project-viewer",
        projects=("project-a",),
    )
    response = client.get("/api/v1/runs")
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "FORBIDDEN"


def test_wildcard_project_scope_remains_usable_for_local_runner(tmp_path):
    _, client, _ = _client(tmp_path, Role.OWNER, "owner-wildcard")
    response = client.get("/api/v1/runs")
    assert response.status_code == 200


def test_background_get_does_not_extend_idle_timeout_but_activity_heartbeat_does(tmp_path):
    app, client, csrf = _client(tmp_path, Role.OWNER, "heartbeat-owner")
    app.config["SESSION_IDLE_TIMEOUT_SECONDS"] = 30
    with client.session_transaction() as stored:
        old_activity = time.time() - 20
        stored["netregress_last_activity"] = old_activity
    # Read-only polling must not extend the idle window.
    assert client.get("/api/v1/runs").status_code == 200
    with client.session_transaction() as stored:
        assert stored["netregress_last_activity"] == old_activity
    response = client.post(
        "/api/v1/auth/activity",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "user-activity-heartbeat"},
        json={},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["active"] is True
    with client.session_transaction() as stored:
        assert stored["netregress_last_activity"] > old_activity


def test_server_enforces_idle_session_expiry(tmp_path):
    app, client, _ = _client(tmp_path, Role.OWNER, "idle-owner")
    app.config["SESSION_IDLE_TIMEOUT_SECONDS"] = 30
    with client.session_transaction() as stored:
        stored["netregress_last_activity"] = time.time() - 31
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "SESSION_EXPIRED"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_attempts_are_rate_limited(tmp_path):
    manager = AuthManager(
        (UserRecord("owner", AuthManager.password_hash(PASSWORD), Role.OWNER),),
        required=True,
    )
    app = create_app(tmp_path / "rate-limit.sqlite", auth_manager=manager)
    app.config.update(TESTING=True)
    client = app.test_client()
    for _ in range(8):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": "incorrect"},
        )
        assert response.status_code == 401
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": "incorrect"},
    )
    assert response.status_code == 429
    assert response.get_json()["error"]["code"] == "RATE_LIMITED"


def test_security_headers_and_api_no_store_are_present(tmp_path):
    _, client, _ = _client(tmp_path, Role.OWNER, "security-owner")
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "no-store" in response.headers["Cache-Control"]


def test_readiness_endpoint_requires_authentication(tmp_path):
    app = create_app(
        tmp_path / "readiness-auth.sqlite",
        auth_manager=AuthManager((), required=True),
    )
    app.config.update(TESTING=True)
    response = app.test_client().get("/api/v1/readiness")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "UNAUTHENTICATED"
