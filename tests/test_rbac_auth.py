import json
from dashboard.app import create_app
from lib.security import AuthManager,UserRecord,Role

def test_password_authentication():
    manager=AuthManager([UserRecord("admin",AuthManager.password_hash("pw"),Role.OWNER)])
    assert manager.authenticate("admin","pw").role is Role.OWNER

def test_api_requires_auth(tmp_path,monkeypatch):
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED","1")
    monkeypatch.setenv("NETREGRESS_AUTH_USERS_JSON",json.dumps([{"username":"admin","password_hash":AuthManager.password_hash("pw"),"role":"OWNER","projects":["*"]}]))
    monkeypatch.setenv("NETREGRESS_SESSION_SECRET","test-secret")
    client=create_app(tmp_path/"db.sqlite").test_client()
    assert client.get("/api/v1/runs").status_code==401


def test_admin_can_create_waiver(tmp_path, monkeypatch):
    import json
    from lib.services import AuthManager
    digest = AuthManager.password_hash("pw")
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED","1")
    monkeypatch.setenv("NETREGRESS_AUTH_USERS_JSON",json.dumps([
        {"username":"admin","password_hash":digest,"role":"ADMIN","projects":["*"]}
    ]))
    monkeypatch.setenv("NETREGRESS_SESSION_SECRET","test-session-secret")
    app = __import__("dashboard.app",fromlist=["create_app"]).create_app(tmp_path / "db.sqlite")
    client = app.test_client()
    response = client.post("/api/v1/auth/login", json={"username":"admin","password":"pw"})
    assert response.status_code == 200
    csrf = response.get_json()["data"]["csrf_token"]
    waiver = client.post("/api/v1/waivers", headers={"X-CSRF-Token": csrf}, json={
        "scope":"RELEASE",
        "target_id":"*",
        "issue_code":"NO_BASELINE",
        "reason":"approved release exception",
    })
    assert waiver.status_code == 201
    assert waiver.get_json()["data"]["issue_code"] == "NO_BASELINE"
