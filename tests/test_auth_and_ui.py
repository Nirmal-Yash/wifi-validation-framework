from __future__ import annotations

import os
import time

os.environ.setdefault("FLASK_TESTING", "1")
os.environ.setdefault("NETFORGE_AUTH_DISABLED", "1")

from dashboard.enterprise_app import app
from dashboard.auth import validate_registration


def test_registration_validation():
    assert validate_registration("ab", "long-enough-password", "long-enough-password")
    assert validate_registration("valid_user", "short", "short")
    assert validate_registration("valid_user", "long-enough-password", "different-password")
    assert validate_registration("valid_user", "long-enough-password", "long-enough-password") is None


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
