from __future__ import annotations

import hmac
import os
import re
import secrets
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from dashboard.app import app
from dashboard.db import connection, ensure_schema

ROLES = {
    "admin": {"view", "execute", "cancel", "topology_edit", "topology_commit", "manage_users", "audit", "artifacts", "settings"},
    "operator": {"view", "execute", "cancel", "topology_edit", "artifacts", "audit"},
    "viewer": {"view", "artifacts"},
}
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _testing_bypass() -> bool:
    return os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1"


def _safe_next(value: str | None) -> str:
    """Accept only local relative redirects; never trust an arbitrary next URL."""
    value = (value or "/").strip()
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _client_ip() -> str:
    # Do not trust X-Forwarded-For unless the deployment explicitly normalizes it.
    return request.remote_addr or "unknown"


def _auth_rate_limited(username: str, ip: str) -> bool:
    with connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS failures FROM auth_attempts
               WHERE success=0 AND created_at >= datetime('now', ?)
               AND (lower(username)=lower(?) OR ip=?)""",
            (f"-{LOCKOUT_MINUTES} minutes", username, ip),
        ).fetchone()
    return int(row["failures"] or 0) >= MAX_FAILED_ATTEMPTS


def _record_auth_attempt(username: str, ip: str, success: bool) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO auth_attempts(username,ip,success) VALUES(?,?,?)",
            (username[:128], ip[:64], 1 if success else 0),
        )
        # Successful authentication clears stale failures for this account/IP.
        if success:
            conn.execute(
                "DELETE FROM auth_attempts WHERE lower(username)=lower(?) AND ip=? AND success=0",
                (username, ip),
            )
        conn.commit()


def ensure_admin():
    ensure_schema()
    username = os.getenv("NETFORGE_ADMIN_USER", "admin").strip() or "admin"
    password = os.getenv("NETFORGE_ADMIN_PASSWORD", "")
    if not password:
        return False
    if len(password) < 12:
        raise RuntimeError("NETFORGE_ADMIN_PASSWORD must contain at least 12 characters")
    with connection() as conn:
        row = conn.execute("SELECT id, role, active FROM users WHERE lower(username)=lower(?)", (username,)).fetchone()
        if row:
            if row["role"] != "admin" or not row["active"]:
                conn.execute("UPDATE users SET role='admin', active=1 WHERE id=?", (row["id"],))
                conn.commit()
            return True
        conn.execute(
            "INSERT INTO users(username,password_hash,role,active) VALUES(?,?,?,1)",
            (username, generate_password_hash(password)),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,actor,message,payload_json) VALUES(?,?,?,?)",
            ("ADMIN_BOOTSTRAP", "system", "Initial administrator account ensured", "{}"),
        )
        conn.commit()
    return True


def validate_registration(username: str, password: str, confirmation: str):
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        return "Username must be 3-32 characters and use only letters, numbers, ., _, or -."
    if len(password) < 12:
        return "Password must contain at least 12 characters."
    if not re.search(r"[A-Z]", password) or not re.search(r"[a-z]", password) or not re.search(r"\d", password):
        return "Password must contain at least one uppercase letter, one lowercase letter, and one number."
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
        cur = conn.execute(
            "INSERT INTO users(username,password_hash,role,active) VALUES(?,?,?,0)",
            (username, generate_password_hash(password), "viewer"),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type,actor,message,payload_json) VALUES(?,?,?,?)",
            ("SIGNUP_REQUEST", username, "New account registration submitted", '{"status":"pending_admin_activation"}'),
        )
        conn.commit()
        return cur.lastrowid, None


def authenticate(username, password):
    username = (username or "").strip()
    ip = _client_ip()
    if _auth_rate_limited(username, ip):
        return None
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username,)).fetchone()
    # Always perform a password-hash check for unknown/inactive accounts when possible
    # to reduce username-enumeration timing differences.
    valid_password = check_password_hash(row["password_hash"], password) if row else check_password_hash(
        generate_password_hash("netforge-invalid-login-placeholder"), password
    )
    valid = bool(row and row["active"] and valid_password)
    _record_auth_attempt(username, ip, valid)
    if not valid:
        return None

    session.clear()
    session.permanent = True
    session["user_id"] = row["id"]
    session["username"] = row["username"]
    session["role"] = row["role"]
    session["csrf"] = secrets.token_urlsafe(32)
    with connection() as conn:
        conn.execute("UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
        conn.execute(
            "INSERT INTO audit_events(event_type,actor,message,payload_json) VALUES(?,?,?,?)",
            ("LOGIN", row["username"], "User authenticated", "{}"),
        )
        conn.commit()
    return dict(row)


def logout():
    session.clear()


def current_user():
    return {"id": session.get("user_id"), "username": session.get("username"), "role": session.get("role")} if session.get("user_id") else None


def can(permission):
    if _testing_bypass():
        return True
    role = session.get("role")
    return role in ROLES and permission in ROLES[role]


def login_required(permission="view"):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if _testing_bypass():
                return fn(*args, **kwargs)
            if not current_user():
                abort(401)
            if not can(permission):
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def csrf_valid(token):
    expected = session.get("csrf", "")
    return bool(token and expected and hmac.compare_digest(str(token), str(expected)))


def bootstrap_required():
    if not ensure_admin():
        raise RuntimeError("NETFORGE_ADMIN_PASSWORD is required before authentication can be enabled")


@app.before_request
def public_auth_pages():
    """Provide unauthenticated sign-in/sign-up entry points before the enterprise gate."""
    if request.path == "/signin":
        return redirect(url_for("netforge_login", next=_safe_next(request.args.get("next"))))
    if request.path != "/signup":
        return None
    if request.method == "GET":
        session.setdefault("signup_csrf", secrets.token_urlsafe(32))
        return render_template("signup.html", csrf=session["signup_csrf"])
    token = request.form.get("csrf", "")
    if not session.get("signup_csrf") or not hmac.compare_digest(token, session.get("signup_csrf", "")):
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
