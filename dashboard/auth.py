from __future__ import annotations

import os
import re
import secrets
from functools import wraps

from flask import abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from dashboard.app import app
from dashboard.db import connection

ROLES = {
    "admin": {"view", "execute", "cancel", "topology_edit", "topology_commit", "manage_users", "audit", "artifacts", "settings"},
    "operator": {"view", "execute", "cancel", "topology_edit", "artifacts", "audit"},
    "viewer": {"view", "artifacts"},
}
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")


def ensure_admin():
    username = os.getenv("NETFORGE_ADMIN_USER", "admin").strip()
    password = os.getenv("NETFORGE_ADMIN_PASSWORD", "").strip()
    if not password:
        return False
    with connection() as conn:
        row = conn.execute("SELECT id, role FROM users WHERE username=?", (username,)).fetchone()
        if row:
            if row["role"] != "admin":
                conn.execute("UPDATE users SET role='admin', active=1 WHERE id=?", (row["id"],))
                conn.commit()
            return True
        conn.execute("INSERT INTO users(username,password_hash,role,active) VALUES(?,?,?,1)", (username, generate_password_hash(password), "admin"))
        conn.execute("INSERT INTO audit_events(event_type,actor,message,payload_json) VALUES(?,?,?,?)", ("ADMIN_BOOTSTRAP", "system", "Initial administrator account ensured", "{}"))
        conn.commit()
    return True


def validate_registration(username: str, password: str, confirmation: str):
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        return "Username must be 3-32 characters and use only letters, numbers, ., _, or -."
    if len(password) < 12:
        return "Password must contain at least 12 characters."
    if password != confirmation:
        return "Passwords do not match."
    if username.lower() in {"admin", "root", "system", "administrator"}:
        return "That username is reserved."
    return None


def register_user(username: str, password: str):
    username = username.strip()
    with connection() as conn:
        if conn.execute("SELECT id FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
            return None, "Username is already registered."
        cur = conn.execute("INSERT INTO users(username,password_hash,role,active) VALUES(?,?,?,0)", (username, generate_password_hash(password), "viewer"))
        conn.execute("INSERT INTO audit_events(event_type,actor,message,payload_json) VALUES(?,?,?,?)", ("SIGNUP_REQUEST", username, "New account registration submitted", "{\"status\":\"pending_admin_activation\"}"))
        conn.commit()
        return cur.lastrowid, None


def authenticate(username, password):
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    if not row or not row["active"] or not check_password_hash(row["password_hash"], password):
        return None
    session.clear()
    session["user_id"] = row["id"]
    session["username"] = row["username"]
    session["role"] = row["role"]
    session["csrf"] = secrets.token_urlsafe(24)
    with connection() as conn:
        conn.execute("UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
        conn.execute("INSERT INTO audit_events(event_type,actor,message,payload_json) VALUES(?,?,?,?)", ("LOGIN", row["username"], "User authenticated", "{}"))
        conn.commit()
    return dict(row)


def logout():
    session.clear()


def current_user():
    return {"id": session.get("user_id"), "username": session.get("username"), "role": session.get("role")} if session.get("user_id") else None


def can(permission):
    if os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1":
        return True
    return session.get("role") in ROLES and permission in ROLES[session["role"]]


def login_required(permission="view"):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1":
                return fn(*args, **kwargs)
            if not current_user():
                abort(401)
            if not can(permission):
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def csrf_valid(token):
    return bool(token) and secrets.compare_digest(token, session.get("csrf", ""))


def bootstrap_required():
    if not ensure_admin():
        raise RuntimeError("NETFORGE_ADMIN_PASSWORD is required before authentication can be enabled")


@app.before_request
def public_auth_pages():
    """Provide unauthenticated sign-in/sign-up entry points before the enterprise gate."""
    if request.path == "/signin":
        return redirect(url_for("netforge_login", next=request.args.get("next", "/")))
    if request.path != "/signup":
        return None
    if request.method == "GET":
        session.setdefault("signup_csrf", secrets.token_urlsafe(24))
        return render_template("signup.html", csrf=session["signup_csrf"])
    if request.form.get("csrf") != session.get("signup_csrf"):
        return render_template("signup.html", error="Your registration form expired. Please try again.", csrf=session.get("signup_csrf", "")), 403
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    confirmation = request.form.get("password_confirmation", "")
    problem = validate_registration(username, password, confirmation)
    if problem:
        return render_template("signup.html", error=problem, csrf=session.get("signup_csrf", "")), 422
    user_id, problem = register_user(username, password)
    if problem:
        return render_template("signup.html", error=problem, csrf=session.get("signup_csrf", "")), 409
    session.pop("signup_csrf", None)
    return render_template("signup.html", success=f"Account #{user_id} created. An administrator must activate it before you can sign in.", csrf=""), 201
