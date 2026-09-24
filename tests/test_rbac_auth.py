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
