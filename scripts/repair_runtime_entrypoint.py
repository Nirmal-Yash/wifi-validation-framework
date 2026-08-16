from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"Patch anchor not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def patch_enterprise_import() -> bool:
    path = ROOT / "dashboard" / "enterprise_app.py"
    old = '''from dashboard.app import (\n    app,\n    commit_draft,\n    create_draft,\n    delete_topology_version,\n    persist_topology,\n    replace_draft,\n    topology_payload,\n)'''
    new = '''# Resolve the canonical Flask application without creating a second app when\n# dashboard/app.py is executed directly as a script.\nimport importlib\nimport sys\n\nif "__main__" in sys.modules and hasattr(sys.modules["__main__"], "app"):\n    _dashboard_app = sys.modules["__main__"]\nelse:\n    _dashboard_app = importlib.import_module("dashboard.app")\n\n# Critical: modules such as dashboard.auth still import dashboard.app. Alias\n# that module name to the already-running application so decorators and\n# before_request hooks are registered on the same Flask instance.\nsys.modules.setdefault("dashboard.app", _dashboard_app)\n\napp = _dashboard_app.app\ncommit_draft = _dashboard_app.commit_draft\ncreate_draft = _dashboard_app.create_draft\ndelete_topology_version = _dashboard_app.delete_topology_version\npersist_topology = _dashboard_app.persist_topology\nreplace_draft = _dashboard_app.replace_draft\ntopology_payload = _dashboard_app.topology_payload'''
    return replace_once(path, old, new)


def patch_enterprise_session_override() -> bool:
    path = ROOT / "dashboard" / "enterprise_app.py"
    old = 'app.secret_key = os.getenv("NETFORGE_SECRET_KEY", "netforge-development-secret")\napp.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("NETFORGE_COOKIE_SECURE", "0") == "1")'
    new = '''# Session/security configuration is owned by dashboard.app. Do not override\n# the production secret or secure-cookie policy from the enterprise module.\napp.config.update(\n    SESSION_COOKIE_HTTPONLY=True,\n    SESSION_COOKIE_SAMESITE=app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),\n    SESSION_COOKIE_SECURE=app.config.get("SESSION_COOKIE_SECURE", False),\n)'''
    return replace_once(path, old, new)


def patch_dockerfile() -> bool:
    path = ROOT / "Dockerfile"
    old = 'CMD ["gunicorn","-w","2","--threads","4","--timeout","120","-b","0.0.0.0:5000","dashboard.enterprise_app:app"]'
    new = 'CMD ["gunicorn","-w","2","--threads","4","--timeout","120","-b","0.0.0.0:5000","dashboard.wsgi:app"]'
    return replace_once(path, old, new)


def patch_compose_healthcheck() -> bool:
    path = ROOT / "docker-compose.yml"
    old = "urlopen('http://127.0.0.1:5000/api/enterprise/health', timeout=3)"
    new = "urlopen('http://127.0.0.1:5000/health', timeout=3)"
    return replace_once(path, old, new)


def patch_service() -> bool:
    path = ROOT / "deploy" / "netforge.service"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if "dashboard.wsgi:app" in text:
        return False
    old = "dashboard.enterprise_app:app"
    if old not in text:
        return False
    path.write_text(text.replace(old, "dashboard.wsgi:app"), encoding="utf-8")
    return True


def create_wsgi() -> bool:
    path = ROOT / "dashboard" / "wsgi.py"
    if path.exists():
        return False
    path.write_text('''"""Canonical WSGI entrypoint for NetForge.\n\nAll deployment modes must import this module so the dashboard and enterprise\ncontrol plane are guaranteed to share the same Flask application instance.\n"""\n\nfrom dashboard.app import app\n\n__all__ = ["app"]\n''', encoding="utf-8")
    return True


def create_run() -> bool:
    path = ROOT / "run.py"
    if path.exists():
        return False
    path.write_text('''"""Canonical local development entrypoint.\n\nRun with: python run.py\n"""\n\nfrom dashboard.app import app\nfrom dashboard.db import ensure_schema\n\n\nif __name__ == "__main__":\n    ensure_schema()\n    print("[*] NetForge Control Plane: http://127.0.0.1:5000")\n    app.run(\n        host="0.0.0.0",\n        port=int(__import__("os").getenv("NETFORGE_PORT", "5000")),\n        debug=__import__("os").getenv("NETFORGE_DEBUG", "0") == "1",\n    )\n''', encoding="utf-8")
    return True


def patch_runtime_diagnostics() -> bool:
    path = ROOT / "dashboard" / "app.py"
    text = path.read_text(encoding="utf-8")
    marker = "# Enterprise control-plane integration: dashboard.app is the canonical local entrypoint."
    if marker not in text:
        raise RuntimeError("Runtime integration marker not found in dashboard/app.py")
    if "def runtime_manifest():" in text:
        return False
    block = '''@app.route('/api/runtime/manifest')\ndef runtime_manifest():\n    required = {\n        '/', '/health', '/topology', '/history', '/operations', '/analytics',\n        '/admin', '/login', '/api/enterprise/summary',\n        '/api/enterprise/health/detailed', '/api/enterprise/executions',\n    }\n    registered = {rule.rule for rule in app.url_map.iter_rules()}\n    missing = sorted(required - registered)\n    return api_ok({\n        'entrypoint': 'dashboard.app',\n        'application_id': id(app),\n        'route_count': len(registered),\n        'required_routes': sorted(required),\n        'missing_routes': missing,\n        'public_auth_intercepts': ['/signin', '/signup'],\n        'status': 'ready' if not missing else 'degraded',\n    })\n\n\n'''
    path.write_text(text.replace(marker, block + marker, 1), encoding="utf-8")
    return True


def patch_app_security_config() -> bool:
    path = ROOT / "dashboard" / "app.py"
    old = "app=Flask(__name__,template_folder=str(TEMPLATE_DIR)); app.config.update(UPLOAD_FOLDER=str(UPLOAD_DIR),MAX_CONTENT_LENGTH=16*1024*1024)"
    new = '''app=Flask(__name__,template_folder=str(TEMPLATE_DIR))\n_secret = os.getenv("NETFORGE_SECRET_KEY")\n_environment = os.getenv("NETFORGE_ENV", "development").lower()\nif not _secret and _environment == "production" and os.getenv("FLASK_TESTING", "0") != "1":\n    raise RuntimeError("NETFORGE_SECRET_KEY is required when NETFORGE_ENV=production")\napp.secret_key = _secret or ("netforge-test-secret" if os.getenv("FLASK_TESTING", "0") == "1" else "netforge-development-secret")\napp.config.update(\n    UPLOAD_FOLDER=str(UPLOAD_DIR),\n    MAX_CONTENT_LENGTH=16*1024*1024,\n    SESSION_COOKIE_HTTPONLY=True,\n    SESSION_COOKIE_SAMESITE="Lax",\n    SESSION_COOKIE_SECURE=os.getenv("NETFORGE_COOKIE_SECURE", "1" if _environment == "production" else "0") == "1",\n    PERMANENT_SESSION_LIFETIME=__import__("datetime").timedelta(hours=8),\n)'''
    return replace_once(path, old, new)


def patch_login_flow() -> bool:
    path = ROOT / "dashboard" / "enterprise_app.py"
    old = '''@app.route("/login", methods=["GET", "POST"])\ndef netforge_login():\n    from dashboard.auth import _safe_next, csrf_valid\n    next_url = _safe_next(request.args.get("next"))\n    if request.method == "GET":\n        session.setdefault("login_csrf", __import__("secrets").token_urlsafe(32))\n        return render_template("login.html", bootstrap_ready=bool(os.getenv("NETFORGE_ADMIN_PASSWORD")), csrf=session["login_csrf"])\n    token = request.form.get("csrf", "")\n    if not session.get("login_csrf") or not csrf_valid(token) and not (os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1"):\n        return render_template("login.html", error="Your sign-in form expired. Please try again.", bootstrap_ready=bool(os.getenv("NETFORGE_ADMIN_PASSWORD")), csrf=session.get("login_csrf", "")), 403\n    username = request.form.get("username", "").strip()\n    password = request.form.get("password", "")\n    if not username or not password:\n        return render_template("login.html", error="Username and password are required", bootstrap_ready=bool(os.getenv("NETFORGE_ADMIN_PASSWORD")), csrf=session.get("login_csrf", "")), 422\n    try:\n        ensure_admin()\n    except RuntimeError as exc:\n        return render_template("login.html", error=str(exc), bootstrap_ready=False, csrf=session.get("login_csrf", "")), 503\n    if not authenticate(username, password):\n        return render_template("login.html", error="Invalid username or password", bootstrap_ready=True, csrf=session.get("login_csrf", "")), 401\n    session.pop("login_csrf", None)\n    audit("LOGIN", username, "User authenticated")\n    return redirect(next_url)\n\n\n@app.route("/logout", methods=["POST"])\ndef netforge_logout():\n    from dashboard.auth import csrf_valid\n    if not csrf_valid(request.form.get("csrf") or request.headers.get("X-CSRF-Token")) and not (os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1"):\n        return error("CSRF_INVALID", "Invalid CSRF token", 403)\n    actor = session.get("username", "unknown")\n    logout()\n    audit("LOGOUT", actor, "User logged out")\n    return redirect("/login")'''
    new = '''@app.route("/login", methods=["GET", "POST"])\ndef netforge_login():\n    from dashboard.auth import _safe_next\n    next_url = _safe_next(request.args.get("next"))\n    if request.method == "GET":\n        session.setdefault("login_csrf", __import__("secrets").token_urlsafe(32))\n        return render_template("login.html", bootstrap_ready=bool(os.getenv("NETFORGE_ADMIN_PASSWORD")), csrf=session["login_csrf"])\n    token = request.form.get("csrf", "")\n    bypass = os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1"\n    if not bypass and (not session.get("login_csrf") or not __import__("hmac").compare_digest(token, session.get("login_csrf", ""))):\n        return render_template("login.html", error="Your sign-in form expired. Please try again.", bootstrap_ready=bool(os.getenv("NETFORGE_ADMIN_PASSWORD")), csrf=session.get("login_csrf", "")), 403\n    username = request.form.get("username", "").strip()\n    password = request.form.get("password", "")\n    if not username or not password:\n        return render_template("login.html", error="Username and password are required", bootstrap_ready=bool(os.getenv("NETFORGE_ADMIN_PASSWORD")), csrf=session.get("login_csrf", "")), 422\n    try:\n        ensure_admin()\n    except RuntimeError as exc:\n        return render_template("login.html", error=str(exc), bootstrap_ready=False, csrf=session.get("login_csrf", "")), 503\n    if not authenticate(username, password):\n        return render_template("login.html", error="Invalid username or password", bootstrap_ready=True, csrf=session.get("login_csrf", "")), 401\n    session.pop("login_csrf", None)\n    audit("LOGIN", username, "User authenticated")\n    return redirect(next_url)\n\n\n@app.route("/logout", methods=["POST"])\ndef netforge_logout():\n    from dashboard.auth import csrf_valid\n    bypass = os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1"\n    if not bypass and not csrf_valid(request.form.get("csrf") or request.headers.get("X-CSRF-Token")):\n        return error("CSRF_INVALID", "Invalid CSRF token", 403)\n    actor = session.get("username", "unknown")\n    logout()\n    audit("LOGOUT", actor, "User logged out")\n    return redirect("/login")'''
    return replace_once(path, old, new)


def patch_manifest_security() -> bool:
    path = ROOT / "dashboard" / "app.py"
    old = "'public_auth_intercepts': ['/signin', '/signup'],"
    new = "'public_auth_intercepts': ['/signin', '/signup'],\n        'authentication': {'session_cookie_httponly': bool(app.config.get('SESSION_COOKIE_HTTPONLY')), 'session_cookie_samesite': app.config.get('SESSION_COOKIE_SAMESITE'), 'session_cookie_secure': bool(app.config.get('SESSION_COOKIE_SECURE')), 'auth_bypass_active': os.getenv('NETFORGE_AUTH_DISABLED', '0') == '1' and os.getenv('FLASK_TESTING', '0') == '1'},"
    return replace_once(path, old, new)


def patch_logout_template() -> bool:
    path = ROOT / "dashboard" / "templates" / "base.html"
    old = '<a href="/logout" class="sidebar-link" style="margin-top:auto"><i class="fa-solid fa-right-from-bracket"></i><span>Logout ({{session.get(\'username\')}})</span></a>'
    new = '<form method="post" action="/logout" style="margin-top:auto"><input type="hidden" name="csrf" value="{{ session.get(\'csrf\',\'\')|e }}"><button type="submit" class="sidebar-link" style="width:100%;background:transparent;border-top:0;border-right:0;border-bottom:0;text-align:left"><i class="fa-solid fa-right-from-bracket"></i><span>Logout ({{session.get(\'username\')}})</span></button></form>'
    return replace_once(path, old, new)


def main() -> None:
    changed = []
    for name, fn in [
        ("enterprise import", patch_enterprise_import),
        ("enterprise session override", patch_enterprise_session_override),
        ("WSGI entrypoint", create_wsgi),
        ("local entrypoint", create_run),
        ("runtime diagnostics", patch_runtime_diagnostics),
        ("application security config", patch_app_security_config),
        ("login/logout flow", patch_login_flow),
        ("runtime security diagnostics", patch_manifest_security),
        ("logout template", patch_logout_template),
        ("Docker entrypoint", patch_dockerfile),
        ("Compose healthcheck", patch_compose_healthcheck),
        ("systemd entrypoint", patch_service),
    ]:
        if fn():
            changed.append(name)
    print("Runtime repair complete:", ", ".join(changed) if changed else "already applied")


if __name__ == "__main__":
    main()
