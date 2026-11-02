import time

from dashboard.app import create_app
from lib.security import AuthManager, Role, UserRecord


PASSWORD = "correct-horse-battery-staple"


def test_legacy_dashboard_routes_enforce_server_idle_timeout(tmp_path):
    manager = AuthManager(
        (UserRecord("owner", AuthManager.password_hash(PASSWORD), Role.OWNER),),
        required=True,
    )
    app = create_app(tmp_path / "legacy-idle.sqlite", auth_manager=manager)
    app.config.update(TESTING=True, SESSION_IDLE_TIMEOUT_SECONDS=30)
    client = app.test_client()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": PASSWORD},
    )
    assert login.status_code == 200
    with client.session_transaction() as stored:
        stored["netregress_last_activity"] = time.time() - 31
    response = client.get("/runs")
    assert response.status_code == 401
    with client.session_transaction() as stored:
        assert "netregress_user" not in stored


def test_legacy_dashboard_rejects_project_scoped_identities(tmp_path):
    manager = AuthManager(
        (UserRecord("scoped-viewer", AuthManager.password_hash(PASSWORD), Role.VIEWER, ("project-a",)),),
        required=True,
    )
    app = create_app(tmp_path / "legacy-scoped.sqlite", auth_manager=manager)
    app.config.update(TESTING=True)
    client = app.test_client()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "scoped-viewer", "password": PASSWORD},
    )
    assert login.status_code == 200
    response = client.get("/runs")
    assert response.status_code == 403
