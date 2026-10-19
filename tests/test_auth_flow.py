from dashboard.app import create_app
from lib.security import AuthManager, Role, UserRecord


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
