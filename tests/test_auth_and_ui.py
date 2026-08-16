from __future__ import annotations

import os
import time

os.environ.setdefault("FLASK_TESTING", "1")
os.environ.setdefault("NETFORGE_AUTH_DISABLED", "1")
os.environ.setdefault("NETFORGE_ADMIN_USER", "ci_auth_admin")
os.environ.setdefault("NETFORGE_ADMIN_PASSWORD", "NetForge-CI-Admin-123")

from dashboard.enterprise_app import app
from dashboard.auth import validate_registration
from dashboard.db import connection, ensure_schema
from werkzeug.security import generate_password_hash


def test_registration_validation():
    assert validate_registration("ab", "long-enough-password", "long-enough-password")
    assert validate_registration("valid_user", "short", "short")
    assert validate_registration("valid_user", "long-enough-password", "different-password")
    assert validate_registration("valid_user", "long-enough-password", "long-enough-password") is not None
    assert validate_registration("Valid_User", "StrongPassword123", "StrongPassword123") is None


def test_signin_and_signup_entry_points():
    client = app.test_client()
    assert client.get("/login").status_code == 200
    assert client.get("/signin").status_code in {301, 302, 303, 307, 308}
    signup = client.get("/signup")
    assert signup.status_code == 200
    assert b"Create Account" in signup.data


def test_signup_creates_pending_viewer():
    client = app.test_client()
    page = client.get("/signup")
    with client.session_transaction() as session:
        token = session["signup_csrf"]
    username = f"ci_signup_{int(time.time() * 1000000)}"
    response = client.post("/signup", data={
        "csrf": token,
        "username": username,
        "password": "NetForge-Test-Password-123",
        "password_confirmation": "NetForge-Test-Password-123",
    })
    assert response.status_code == 201
    assert b"administrator must activate" in response.data


def test_control_plane_pages_render_in_test_mode():
    client = app.test_client()
    assert client.get("/operations").status_code == 200
    assert client.get("/analytics").status_code == 200
    assert client.get("/admin").status_code == 200


def _real_auth_client():
    os.environ["NETFORGE_AUTH_DISABLED"] = "0"
    ensure_schema()
    with connection() as conn:
        conn.execute("DELETE FROM users WHERE username IN ('ci_auth_viewer', 'ci_auth_admin')")
        conn.execute("INSERT INTO users(username,password_hash,role,active) VALUES(?,?,?,?)", ("ci_auth_viewer", generate_password_hash("Viewer-Password-123"), "viewer", 1))
        conn.commit()
    return app.test_client()


def test_real_login_requires_csrf_and_establishes_session():
    client = _real_auth_client()
    page = client.get("/login")
    assert page.status_code == 200
    with client.session_transaction() as session:
        token = session["login_csrf"]
    bad = client.post("/login", data={"username": "ci_auth_admin", "password": "NetForge-CI-Admin-123", "csrf": "wrong"})
    assert bad.status_code == 403
    good = client.post("/login?next=https://evil.example", data={"username": "ci_auth_admin", "password": "NetForge-CI-Admin-123", "csrf": token})
    assert good.status_code in {301, 302, 303, 307, 308}
    assert good.headers["Location"].endswith("/")
    with client.session_transaction() as session:
        assert session["username"] == "ci_auth_admin"
        assert session["role"] == "admin"
        assert session.get("csrf")
        assert "login_csrf" not in session


def test_real_auth_requires_login_and_logout_is_csrf_protected():
    client = _real_auth_client()
    assert client.get("/api/enterprise/summary").status_code == 401
    client.get("/login")
    with client.session_transaction() as session:
        login_token = session["login_csrf"]
    assert client.post("/login", data={"username": "ci_auth_admin", "password": "NetForge-CI-Admin-123", "csrf": login_token}).status_code in {301, 302, 303, 307, 308}
    assert client.post("/logout").status_code == 403
    with client.session_transaction() as session:
        csrf = session["csrf"]
    assert client.post("/logout", data={"csrf": csrf}).status_code in {301, 302, 303, 307, 308}
    with client.session_transaction() as session:
        assert not session.get("user_id")
