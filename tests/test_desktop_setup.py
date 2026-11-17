from __future__ import annotations

from dashboard.app import create_app
from lib.security import AuthManager
from lib.services.identity import IdentityStore
from lib.repositories import SQLiteDatabase


PASSWORD = "desktop-owner-password-2026"


def make_client(tmp_path):
    app = create_app(
        tmp_path / "desktop-setup.sqlite",
        auth_manager=AuthManager((), required=True),
    )
    app.config.update(TESTING=True)
    return app.test_client()


def test_first_run_setup_is_available_only_before_first_account(tmp_path):
    client = make_client(tmp_path)

    status = client.get("/api/v1/setup/status")
    assert status.status_code == 200
    assert status.get_json()["data"]["first_run_required"] is True

    created = client.post(
        "/api/v1/setup/owner",
        json={"username": "owner", "password": PASSWORD},
        headers={"Origin": "tauri://localhost"},
    )
    assert created.status_code == 200
    assert created.get_json()["data"] == {
        "username": "owner",
        "global_role": "OWNER",
        "first_run_required": False,
    }

    status_after = client.get("/api/v1/setup/status")
    assert status_after.get_json()["data"]["first_run_required"] is False

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.get_json()["data"]["role"] == "OWNER"
    assert login.get_json()["data"]["projects"] == ["*"]


def test_first_owner_creation_is_atomic_and_only_happens_once(tmp_path):
    client = make_client(tmp_path)
    first = client.post(
        "/api/v1/setup/owner",
        json={"username": "owner", "password": PASSWORD},
    )
    second = client.post(
        "/api/v1/setup/owner",
        json={"username": "another-owner", "password": PASSWORD},
    )
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "SETUP_ALREADY_COMPLETED"


def test_first_run_setup_rejects_remote_clients(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/v1/setup/owner",
        json={"username": "owner", "password": PASSWORD},
        environ_base={"REMOTE_ADDR": "192.0.2.10"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "LOCAL_SETUP_ONLY"
    assert client.get("/api/v1/setup/status").get_json()["data"]["first_run_required"] is True


def test_first_run_setup_rejects_untrusted_web_origins(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/v1/setup/owner",
        json={"username": "owner", "password": PASSWORD},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "UNTRUSTED_ORIGIN"


def test_first_run_setup_enforces_password_policy_and_username_policy(tmp_path):
    client = make_client(tmp_path)
    weak_password = client.post(
        "/api/v1/setup/owner",
        json={"username": "owner", "password": "short"},
    )
    invalid_username = client.post(
        "/api/v1/setup/owner",
        json={"username": "../owner", "password": PASSWORD},
    )
    assert weak_password.status_code == 400
    assert invalid_username.status_code == 400
    assert client.get("/api/v1/setup/status").get_json()["data"]["first_run_required"] is True


def test_first_run_setup_is_disabled_when_environment_bootstrap_users_exist(tmp_path):
    manager = AuthManager((), required=True)
    app = create_app(tmp_path / "configured.sqlite", auth_manager=manager)
    app.config.update(TESTING=True)
    client = app.test_client()

    # A configured user is already present in the persistent store.
    database = SQLiteDatabase(tmp_path / "configured.sqlite")
    database.initialize()
    IdentityStore(database).bootstrap_first_owner(
        "owner", AuthManager.password_hash(PASSWORD), actor="test",
    )
    assert client.get("/api/v1/setup/status").get_json()["data"]["first_run_required"] is False


def test_desktop_api_cors_is_exact_origin_and_credentialed(tmp_path):
    client = make_client(tmp_path)
    allowed = client.options(
        "/api/v1/setup/owner",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert allowed.headers.get("Access-Control-Allow-Origin") == "tauri://localhost"
    assert allowed.headers.get("Access-Control-Allow-Credentials") == "true"
    assert "POST" in allowed.headers.get("Access-Control-Allow-Methods", "")

    denied = client.options(
        "/api/v1/setup/owner",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert denied.headers.get("Access-Control-Allow-Origin") is None
