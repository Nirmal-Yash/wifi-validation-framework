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
    if "def runtime_manifest():" in text:
        return False
    marker = "# Enterprise control-plane integration: dashboard.app is the canonical local entrypoint."
    if marker not in text:
        raise RuntimeError("Runtime integration marker not found in dashboard/app.py")
    block = '''@app.route('/api/runtime/manifest')\ndef runtime_manifest():\n    required = {\n        '/', '/health', '/topology', '/history', '/operations', '/analytics',\n        '/admin', '/login', '/signup', '/signin', '/api/enterprise/summary',\n        '/api/enterprise/health/detailed', '/api/enterprise/executions',\n    }\n    registered = {rule.rule for rule in app.url_map.iter_rules()}\n    missing = sorted(required - registered)\n    return api_ok({\n        'entrypoint': 'dashboard.app',\n        'application_id': id(app),\n        'route_count': len(registered),\n        'required_routes': sorted(required),\n        'missing_routes': missing,\n        'status': 'ready' if not missing else 'degraded',\n    })\n\n\n'''
    path.write_text(text.replace(marker, block + marker, 1), encoding="utf-8")
    return True


def main() -> None:
    changed = []
    for name, fn in [
        ("enterprise import", patch_enterprise_import),
        ("WSGI entrypoint", create_wsgi),
        ("local entrypoint", create_run),
        ("runtime diagnostics", patch_runtime_diagnostics),
        ("Docker entrypoint", patch_dockerfile),
        ("Compose healthcheck", patch_compose_healthcheck),
        ("systemd entrypoint", patch_service),
    ]:
        if fn():
            changed.append(name)
    print("Runtime repair complete:", ", ".join(changed) if changed else "already applied")


if __name__ == "__main__":
    main()
