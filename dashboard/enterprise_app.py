from __future__ import annotations

import csv
import io
import json
import os
from functools import wraps
from pathlib import Path

from flask import abort, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import generate_password_hash

# Resolve the canonical Flask application without creating a second app when
# dashboard/app.py is executed directly as a script.
import importlib
import sys

if "__main__" in sys.modules and hasattr(sys.modules["__main__"], "app"):
    _dashboard_app = sys.modules["__main__"]
else:
    _dashboard_app = importlib.import_module("dashboard.app")

# Critical: modules such as dashboard.auth still import dashboard.app. Alias
# that module name to the already-running application so decorators and
# before_request hooks are registered on the same Flask instance.
sys.modules.setdefault("dashboard.app", _dashboard_app)

app = _dashboard_app.app
commit_draft = _dashboard_app.commit_draft
create_draft = _dashboard_app.create_draft
delete_topology_version = _dashboard_app.delete_topology_version
persist_topology = _dashboard_app.persist_topology
replace_draft = _dashboard_app.replace_draft
topology_payload = _dashboard_app.topology_payload
from dashboard.auth import ROLES, authenticate, can, csrf_valid, current_user, ensure_admin, logout
from dashboard.db import connection, ensure_schema
from engine.execution_store import audit, get_execution, list_executions, mark_cancel_requested, record_metric
from engine.orchestrator import orchestrator
from engine.regression_engine import analyze_execution, compute_baseline

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "executions"
# Session/security configuration is owned by dashboard.app. Do not override
# the production secret or secure-cookie policy from the enterprise module.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),
    SESSION_COOKIE_SECURE=app.config.get("SESSION_COOKIE_SECURE", False),
)


def error(code, message, status=400, details=None):
    return jsonify({"success": False, "error": {"code": code, "message": message, "details": details or {}}}), status


def ok(data=None, status=200):
    payload = {"success": True}
    payload.update(data or {})
    return jsonify(payload), status


def protected(permission="view"):
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1":
                return fn(*args, **kwargs)
            if not current_user():
                if request.path.startswith("/api/"):
                    return error("AUTH_REQUIRED", "Authentication is required", 401)
                return redirect(url_for("netforge_login", next=request.full_path))
            if not can(permission):
                return error("FORBIDDEN", "Insufficient permission", 403) if request.path.startswith("/api/") else abort(403)
            return fn(*args, **kwargs)
        return inner
    return deco


def csrf_guard():
    if os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1":
        return True
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf")
    return csrf_valid(token)


@app.before_request
def enterprise_auth_gate():
    if request.endpoint in {"netforge_login", "netforge_logout", "netforge_health"} or request.path.startswith("/static/") or request.path == "/health":
        return None
    if os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1":
        return None
    if not current_user():
        if request.path.startswith("/api/"):
            return error("AUTH_REQUIRED", "Authentication is required", 401)
        return redirect(url_for("netforge_login", next=request.full_path))
    if request.path.startswith("/api/topologies") and request.method != "GET":
        if not can("topology_edit"):
            return error("FORBIDDEN", "Topology editing permission is required", 403)
        if not csrf_guard():
            return error("CSRF_INVALID", "Invalid CSRF token", 403)
    return None


@app.route("/login", methods=["GET", "POST"])
def netforge_login():
    from dashboard.auth import _safe_next
    next_url = _safe_next(request.args.get("next"))
    if request.method == "GET":
        session.setdefault("login_csrf", __import__("secrets").token_urlsafe(32))
        return render_template("login.html", bootstrap_ready=bool(os.getenv("NETFORGE_ADMIN_PASSWORD")), csrf=session["login_csrf"])
    token = request.form.get("csrf", "")
    bypass = os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1"
    if not bypass and (not session.get("login_csrf") or not __import__("hmac").compare_digest(token, session.get("login_csrf", ""))):
        return render_template("login.html", error="Your sign-in form expired. Please try again.", bootstrap_ready=bool(os.getenv("NETFORGE_ADMIN_PASSWORD")), csrf=session.get("login_csrf", "")), 403
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not username or not password:
        return render_template("login.html", error="Username and password are required", bootstrap_ready=bool(os.getenv("NETFORGE_ADMIN_PASSWORD")), csrf=session.get("login_csrf", "")), 422
    try:
        ensure_admin()
    except RuntimeError as exc:
        return render_template("login.html", error=str(exc), bootstrap_ready=False, csrf=session.get("login_csrf", "")), 503
    if not authenticate(username, password):
        return render_template("login.html", error="Invalid username or password", bootstrap_ready=True, csrf=session.get("login_csrf", "")), 401
    session.pop("login_csrf", None)
    audit("LOGIN", username, "User authenticated")
    return redirect(next_url)


@app.route("/logout", methods=["POST"])
def netforge_logout():
    from dashboard.auth import csrf_valid
    bypass = os.getenv("NETFORGE_AUTH_DISABLED", "0") == "1" and os.getenv("FLASK_TESTING", "0") == "1"
    if not bypass and not csrf_valid(request.form.get("csrf") or request.headers.get("X-CSRF-Token")):
        return error("CSRF_INVALID", "Invalid CSRF token", 403)
    actor = session.get("username", "unknown")
    logout()
    audit("LOGOUT", actor, "User logged out")
    return redirect("/login")


@app.route("/operations")
def operations():
    return render_template("operations.html", user=current_user(), csrf=session.get("csrf", ""))


@app.route("/analytics")
def analytics():
    return render_template("analytics.html", user=current_user(), csrf=session.get("csrf", ""))


@app.route("/admin")
def admin():
    if not can("manage_users"):
        abort(403)
    with connection() as conn:
        users = [dict(r) for r in conn.execute("SELECT id,username,role,active,created_at,last_login_at FROM users ORDER BY username")]
        audit_rows = [dict(r) for r in conn.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT 200")]
    return render_template("admin.html", user=current_user(), csrf=session.get("csrf", ""), users=users, audit_rows=audit_rows, roles=sorted(ROLES))


@app.route("/api/enterprise/summary")
@protected()
def enterprise_summary():
    with connection() as conn:
        e = conn.execute("""SELECT COUNT(*) total,
            SUM(CASE WHEN status='PASSED' THEN 1 ELSE 0 END) passed,
            SUM(CASE WHEN status IN ('FAILED','ERROR') THEN 1 ELSE 0 END) failed,
            SUM(CASE WHEN status IN ('QUEUED','RUNNING') THEN 1 ELSE 0 END) active,
            SUM(CASE WHEN status='CANCELLED' THEN 1 ELSE 0 END) cancelled,
            AVG(CASE WHEN finished_at IS NOT NULL AND started_at IS NOT NULL THEN (julianday(finished_at)-julianday(started_at))*86400 END) avg_duration
            FROM executions""").fetchone()
        metrics = conn.execute("SELECT metric_name,AVG(metric_value) avg_value,MIN(metric_value) min_value,MAX(metric_value) max_value,COUNT(*) samples FROM execution_metrics GROUP BY metric_name ORDER BY metric_name").fetchall()
        regressions = conn.execute("SELECT COUNT(*) c FROM regressions WHERE created_at >= datetime('now','-7 days')").fetchone()["c"]
        topology_count = conn.execute("SELECT COUNT(*) c FROM topologies").fetchone()["c"]
        active_topologies = conn.execute("SELECT COUNT(*) c FROM topology_versions WHERE status='ACTIVE'").fetchone()["c"]
    total = e["total"] or 0; passed = e["passed"] or 0
    return ok({"summary": {"executions": total, "passed": passed, "failed": e["failed"] or 0, "active": e["active"] or 0, "cancelled": e["cancelled"] or 0, "pass_rate": round(passed * 100 / total, 1) if total else 0, "regressions_7d": regressions, "topologies": topology_count, "active_topologies": active_topologies, "avg_duration_seconds": round(float(e["avg_duration"] or 0), 2)}, "metrics": [dict(r) for r in metrics]})


@app.route("/api/enterprise/health/detailed")
@protected()
def detailed_health():
    checks = {}
    with connection() as conn:
        conn.execute("SELECT 1").fetchone(); checks["database"] = "ok"
        checks["schema"] = "ok" if conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] >= 10 else "degraded"
    checks["artifact_store"] = "ok" if ARTIFACT_ROOT.exists() and os.access(ARTIFACT_ROOT, os.W_OK) else "degraded"
    checks["execution_worker"] = "ok"
    return ok({"service": "netforge-control-plane", "status": "healthy" if all(v == "ok" for v in checks.values()) else "degraded", "checks": checks})


@app.route("/api/enterprise/executions")
@protected()
def enterprise_executions():
    status = request.args.get("status") or None
    limit = min(int(request.args.get("limit", 100)), 500)
    return ok({"executions": list_executions(limit, status)})


@app.route("/api/enterprise/executions/<int:eid>")
@protected()
def enterprise_execution_detail(eid):
    item = get_execution(eid)
    if not item: return error("EXECUTION_NOT_FOUND", "Execution does not exist", 404)
    return ok({"execution": item})


@app.route("/api/enterprise/executions/<int:eid>/results")
@protected()
def execution_results(eid):
    if not get_execution(eid): return error("EXECUTION_NOT_FOUND", "Execution does not exist", 404)
    status = request.args.get("status")
    with connection() as conn:
        sql = "SELECT * FROM test_results WHERE execution_id=?"; params = [eid]
        if status: sql += " AND status=?"; params.append(status.upper())
        sql += " ORDER BY id"
        rows = [dict(r) for r in conn.execute(sql, params)]
    return ok({"results": rows})


@app.route("/api/enterprise/executions/<int:eid>/events")
@protected()
def execution_events(eid):
    if not get_execution(eid): return error("EXECUTION_NOT_FOUND", "Execution does not exist", 404)
    with connection() as conn: rows = [dict(r) for r in conn.execute("SELECT * FROM execution_events WHERE execution_id=? ORDER BY id DESC LIMIT 500", (eid,))]
    return ok({"events": rows})


@app.route("/api/enterprise/executions/<int:eid>/artifacts")
@protected("artifacts")
def execution_artifacts(eid):
    if not get_execution(eid): return error("EXECUTION_NOT_FOUND", "Execution does not exist", 404)
    with connection() as conn: rows = [dict(r) for r in conn.execute("SELECT * FROM evidence WHERE execution_id=? ORDER BY id DESC", (eid,))]
    return ok({"artifacts": rows})


@app.route("/api/enterprise/executions", methods=["POST"])
@protected("execute")
def enterprise_create_execution():
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    p = request.get_json(silent=True) or {}; args = p.get("pytest_args") or ["tests/", "-m", "live", "-v"]
    if not isinstance(args, list) or not all(isinstance(x, str) for x in args): return error("INVALID_ARGS", "pytest_args must be a string array", 422)
    forbidden = [";", "&&", "||", "|", ">", "<", "`", "$("]
    if any(any(x in arg for x in forbidden) for arg in args): return error("UNSAFE_ARGS", "Shell operators are not permitted", 422)
    fw = str(p.get("firmware_version") or "1.0.0").strip()[:80]; suite = str(p.get("suite_name") or "live").strip()[:120]; env = str(p.get("environment") or "tier1").strip()[:40]
    try: eid = orchestrator.submit(fw, suite, session.get("username", "api"), env, str(p.get("notes") or "")[:500], args)
    except Exception as exc: return error("EXECUTION_CREATE_FAILED", str(exc), 500)
    return ok({"execution_id": eid, "status": "QUEUED"}, 202)


@app.route("/api/enterprise/executions/<int:eid>/cancel", methods=["POST"])
@protected("cancel")
def enterprise_cancel(eid):
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    if not mark_cancel_requested(eid): return error("CANCEL_REJECTED", "Execution is not cancellable", 409)
    orchestrator.cancel(eid); audit("EXECUTION_CANCEL", session.get("username", "unknown"), f"Execution #{eid} cancellation requested", {"execution_id": eid})
    return ok({"execution_id": eid, "cancel_requested": True}, 202)


@app.route("/api/enterprise/executions/<int:eid>/retry", methods=["POST"])
@protected("execute")
def enterprise_retry(eid):
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    old = get_execution(eid)
    if not old: return error("EXECUTION_NOT_FOUND", "Execution does not exist", 404)
    if old["status"] in {"QUEUED", "RUNNING"}: return error("RETRY_NOT_ALLOWED", "Only completed executions can be retried", 409)
    args = json.loads(old.get("pytest_args_json") or "null") if old.get("pytest_args_json") else None
    new = orchestrator.submit(old["firmware_version"], old.get("suite_name") or "live", session.get("username", "unknown"), old.get("environment") or "tier1", f"Retry of execution #{eid}", args)
    audit("EXECUTION_RETRY", session.get("username", "unknown"), f"Execution #{new} retried from #{eid}", {"source_execution": eid, "new_execution": new})
    return ok({"execution_id": new, "source_execution_id": eid}, 202)


@app.route("/api/enterprise/executions/<int:eid>/analyze", methods=["POST"])
@protected("execute")
def enterprise_analyze(eid):
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    try: threshold = float((request.get_json(silent=True) or {}).get("threshold_percent", 10))
    except (TypeError, ValueError): return error("INVALID_THRESHOLD", "threshold_percent must be numeric", 422)
    if not 0 < threshold <= 100: return error("INVALID_THRESHOLD", "threshold_percent must be between 0 and 100", 422)
    try: return ok({"regressions": analyze_execution(eid, threshold)})
    except Exception as exc: return error("ANALYSIS_FAILED", str(exc), 500)


@app.route("/api/enterprise/metrics", methods=["POST"])
@protected("execute")
def enterprise_metric():
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    p = request.get_json(silent=True) or {}
    try: eid = int(p["execution_id"]); value = float(p["value"])
    except (KeyError, TypeError, ValueError): return error("INVALID_METRIC", "execution_id and numeric value are required", 422)
    if not get_execution(eid): return error("EXECUTION_NOT_FOUND", "Execution does not exist", 404)
    mid = record_metric(eid, str(p.get("metric_name") or "custom").strip()[:120], value, str(p.get("unit") or "").strip()[:32])
    return ok({"metric_id": mid}, 201)


@app.route("/api/enterprise/analytics/trends")
@protected()
def analytics_trends():
    days = max(1, min(int(request.args.get("days", 30)), 365))
    with connection() as conn:
        outcomes = [dict(r) for r in conn.execute("""SELECT date(created_at) day,COUNT(*) total,
            SUM(CASE WHEN status='PASSED' THEN 1 ELSE 0 END) passed,
            SUM(CASE WHEN status IN ('FAILED','ERROR') THEN 1 ELSE 0 END) failed,
            SUM(CASE WHEN status='CANCELLED' THEN 1 ELSE 0 END) cancelled
            FROM executions WHERE created_at >= datetime('now', ?) GROUP BY date(created_at) ORDER BY day""", (f"-{days} days",))]
        metrics = [dict(r) for r in conn.execute("""SELECT metric_name,date(timestamp) day,AVG(metric_value) value,COUNT(*) samples
            FROM execution_metrics WHERE timestamp >= datetime('now', ?) GROUP BY metric_name,date(timestamp) ORDER BY day""", (f"-{days} days",))]
    return ok({"days": days, "outcomes": outcomes, "metrics": metrics})


@app.route("/api/enterprise/regressions")
@protected()
def regressions():
    severity = request.args.get("severity"); limit = max(1, min(int(request.args.get("limit", 200)), 500))
    with connection() as conn:
        sql = """SELECT r.id,r.execution_id,r.test_name,r.baseline_status,r.candidate_status,r.severity,r.created_at,
            rm.metric_name,rm.baseline_value,rm.current_value,rm.delta_percent,rm.threshold_percent
            FROM regressions r LEFT JOIN regression_metrics rm ON rm.regression_id=r.id"""; params = []
        if severity: sql += " WHERE r.severity=?"; params.append(severity.upper())
        sql += " ORDER BY r.id DESC LIMIT ?"; params.append(limit)
        rows = [dict(r) for r in conn.execute(sql, params)]
    return ok({"regressions": rows})


@app.route("/api/enterprise/baselines")
@protected()
def baselines():
    with connection() as conn: rows = [dict(r) for r in conn.execute("""SELECT b.*,COUNT(bm.id) metric_count FROM baselines b
        LEFT JOIN baseline_metrics bm ON bm.baseline_id=b.id GROUP BY b.id ORDER BY b.id DESC""")]
    return ok({"baselines": rows})


@app.route("/api/enterprise/baselines/build", methods=["POST"])
@protected("execute")
def build_baseline():
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    p = request.get_json(silent=True) or {}; name = str(p.get("name") or "rolling").strip()[:100]; firmware = str(p.get("firmware_version") or "rolling").strip()[:80]
    window = max(2, min(int(p.get("window", 10)), 100)); threshold = float(p.get("threshold_percent", 10)); metrics = p.get("metrics") or []
    if not metrics:
        with connection() as conn: metrics = [r["metric_name"] for r in conn.execute("SELECT DISTINCT metric_name FROM execution_metrics ORDER BY metric_name")]
    if not metrics: return error("NO_METRICS", "No metrics are available to build a baseline", 409)
    with connection() as conn:
        conn.execute("INSERT OR IGNORE INTO firmware_metadata(firmware_version) VALUES (?)", (firmware,)); conn.execute("INSERT OR IGNORE INTO baselines(name,firmware_version) VALUES(?,?)", (name, firmware))
        baseline_id = conn.execute("SELECT id FROM baselines WHERE name=? AND firmware_version=?", (name, firmware)).fetchone()["id"]; built = []
        for metric in metrics:
            item = compute_baseline(str(metric), window=window)
            if not item: continue
            conn.execute("""INSERT INTO baseline_metrics(baseline_id,metric_name,baseline_value,std_deviation,sample_count,window_size,threshold_percent,direction)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(baseline_id,metric_name) DO UPDATE SET baseline_value=excluded.baseline_value,
                std_deviation=excluded.std_deviation,sample_count=excluded.sample_count,window_size=excluded.window_size,
                threshold_percent=excluded.threshold_percent,direction=excluded.direction,computed_at=CURRENT_TIMESTAMP""",
                (baseline_id, metric, item["baseline_value"], item["std_deviation"], item["sample_count"], window, threshold, item["direction"]))
            built.append({"metric_name": metric, **item})
        conn.commit()
    audit("BASELINE_BUILT", session.get("username", "unknown"), f"Built baseline {name}", {"baseline_id": baseline_id, "metrics": len(built)})
    return ok({"baseline_id": baseline_id, "name": name, "firmware_version": firmware, "metrics": built}, 201)


@app.route("/api/enterprise/artifacts/<int:eid>/<path:name>")
@protected("artifacts")
def enterprise_artifact(eid, name):
    with connection() as conn: row = conn.execute("SELECT path,sha256 FROM evidence WHERE execution_id=? AND path=?", (eid, name)).fetchone()
    if not row: return error("ARTIFACT_NOT_FOUND", "Artifact does not exist", 404)
    path = (ROOT / row["path"]).resolve()
    if ROOT.resolve() not in path.parents: return error("ARTIFACT_PATH_INVALID", "Invalid artifact path", 400)
    if not path.exists(): return error("ARTIFACT_MISSING", "Artifact file is missing", 410)
    return send_file(path, as_attachment=True, download_name=path.name)


@app.route("/api/enterprise/audit")
@protected("audit")
def enterprise_audit():
    event_type = request.args.get("event_type"); limit = max(1, min(int(request.args.get("limit", 300)), 1000))
    with connection() as conn:
        sql = "SELECT * FROM audit_events"; params = []
        if event_type: sql += " WHERE event_type=?"; params.append(event_type)
        sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
        rows = [dict(r) for r in conn.execute(sql, params)]
    return ok({"events": rows})


@app.route("/api/enterprise/users")
@protected("manage_users")
def enterprise_users():
    with connection() as conn: rows = [dict(r) for r in conn.execute("SELECT id,username,role,active,created_at,last_login_at FROM users ORDER BY username")]
    return ok({"users": rows})


@app.route("/api/enterprise/users", methods=["POST"])
@protected("manage_users")
def enterprise_user_create():
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    p = request.get_json(silent=True) or {}; username = str(p.get("username") or "").strip(); password = str(p.get("password") or ""); role = str(p.get("role") or "viewer")
    if len(username) < 3 or len(username) > 80 or len(password) < 12 or role not in ROLES: return error("INVALID_USER", "Username/password/role validation failed", 422)
    with connection() as conn:
        try: conn.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)", (username, generate_password_hash(password), role)); conn.commit()
        except Exception: return error("USER_EXISTS", "Username already exists", 409)
    audit("USER_CREATED", session.get("username", "unknown"), f"Created user {username}", {"role": role}); return ok({"username": username, "role": role}, 201)


@app.route("/api/enterprise/users/<int:user_id>", methods=["PATCH", "DELETE"])
@protected("manage_users")
def enterprise_user_update(user_id):
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    if request.method == "DELETE":
        if current_user().get("id") == user_id: return error("SELF_DELETE", "You cannot delete your own account", 409)
        with connection() as conn: cur = conn.execute("DELETE FROM users WHERE id=?", (user_id,)); conn.commit()
        if not cur.rowcount: return error("USER_NOT_FOUND", "User does not exist", 404)
        audit("USER_DELETED", session.get("username", "unknown"), f"Deleted user #{user_id}", {"user_id": user_id}); return ok({"deleted": True})
    p = request.get_json(silent=True) or {}; sets = []; vals = []
    if "role" in p and p["role"] in ROLES: sets.append("role=?"); vals.append(p["role"])
    if "active" in p and isinstance(p["active"], bool):
        if current_user().get("id") == user_id and not p["active"]: return error("SELF_DISABLE", "You cannot disable your own account", 409)
        sets.append("active=?"); vals.append(int(p["active"]))
    if "password" in p and isinstance(p["password"], str) and len(p["password"]) >= 12: sets.append("password_hash=?"); vals.append(generate_password_hash(p["password"]))
    if not sets: return error("NO_CHANGES", "No valid changes supplied", 422)
    vals.append(user_id)
    with connection() as conn: cur = conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", vals); conn.commit()
    if not cur.rowcount: return error("USER_NOT_FOUND", "User does not exist", 404)
    audit("USER_UPDATED", session.get("username", "unknown"), f"Updated user #{user_id}", {k: v for k, v in p.items() if k != "password"}); return ok({"updated": True})


@app.route("/api/enterprise/topology")
@protected()
def enterprise_topology():
    return ok(topology_payload(request.args.get("version_id", type=int)))


@app.route("/api/enterprise/topology/import", methods=["POST"])
@protected("topology_edit")
def enterprise_topology_import():
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    p = request.get_json(silent=True) or {}
    try: result = persist_topology(p.get("name", "imported"), p.get("nodes") or [], p.get("edges") or [], p.get("source", "import"))
    except Exception as exc: return error("TOPOLOGY_IMPORT_FAILED", str(exc), 422)
    audit("TOPOLOGY_IMPORTED", session.get("username", "unknown"), f"Imported topology {result['name']}", result); return ok(result, 201)


@app.route("/api/enterprise/topology/draft", methods=["POST"])
@protected("topology_edit")
def enterprise_topology_draft():
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    p = request.get_json(silent=True) or {}
    try: result = create_draft(int(p["topology_id"]), p.get("nodes"), p.get("edges"))
    except Exception as exc: return error("DRAFT_CREATE_FAILED", str(exc), 422)
    audit("TOPOLOGY_DRAFT_CREATED", session.get("username", "unknown"), f"Created topology draft #{result['id']}", result); return ok(result, 201)


@app.route("/api/enterprise/topology/draft/<int:version_id>", methods=["PUT", "POST"])
@protected("topology_edit")
def enterprise_topology_draft_update(version_id):
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    p = request.get_json(silent=True) or {}
    try: result = replace_draft(version_id, p.get("nodes") or [], p.get("edges") or [])
    except Exception as exc: return error("DRAFT_UPDATE_FAILED", str(exc), 422)
    return ok(result)


@app.route("/api/enterprise/topology/draft/<int:version_id>/commit", methods=["POST"])
@protected("topology_commit")
def enterprise_topology_commit(version_id):
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    try: result = commit_draft(version_id)
    except Exception as exc: return error("TOPOLOGY_COMMIT_FAILED", str(exc), 422)
    audit("TOPOLOGY_COMMITTED", session.get("username", "unknown"), f"Committed topology version #{version_id}", result); return ok(result)


@app.route("/api/enterprise/topology/<int:topology_id>/versions/<int:version_id>", methods=["DELETE"])
@protected("topology_edit")
def enterprise_topology_delete(topology_id, version_id):
    if not csrf_guard(): return error("CSRF_INVALID", "Invalid CSRF token", 403)
    try: result = delete_topology_version(topology_id, version_id)
    except Exception as exc: return error("TOPOLOGY_DELETE_FAILED", str(exc), 422)
    audit("TOPOLOGY_VERSION_DELETED", session.get("username", "unknown"), f"Deleted topology version #{version_id}", result); return ok(result)


@app.route("/api/enterprise/export/execution/<int:eid>")
@protected("artifacts")
def export_execution(eid):
    item = get_execution(eid)
    if not item: return error("EXECUTION_NOT_FOUND", "Execution does not exist", 404)
    return send_file(io.BytesIO(json.dumps(item, indent=2, default=str).encode()), mimetype="application/json", as_attachment=True, download_name=f"netforge-execution-{eid}.json")


@app.route("/api/enterprise/export/regressions.csv")
@protected("audit")
def export_regressions_csv():
    with connection() as conn:
        rows = [dict(r) for r in conn.execute("""SELECT r.id,r.execution_id,r.severity,r.created_at,rm.metric_name,rm.baseline_value,rm.current_value,rm.delta_percent,rm.threshold_percent
            FROM regressions r LEFT JOIN regression_metrics rm ON rm.regression_id=r.id ORDER BY r.id DESC""")]
    output = io.StringIO(); fields = ["id","execution_id","severity","created_at","metric_name","baseline_value","current_value","delta_percent","threshold_percent"]; writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype="text/csv", as_attachment=True, download_name="netforge-regressions.csv")


@app.route("/api/enterprise/health")
def netforge_health():
    ensure_schema(); return ok({"service": "netforge", "status": "healthy", "auth_configured": bool(os.getenv("NETFORGE_ADMIN_PASSWORD"))})
