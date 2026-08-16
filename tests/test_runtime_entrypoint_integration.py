from __future__ import annotations
import os
os.environ.setdefault("FLASK_TESTING", "1")
os.environ.setdefault("NETFORGE_AUTH_DISABLED", "1")
from dashboard.app import app

# This test intentionally imports dashboard.app, the same entrypoint used by `python -m dashboard.app`.
def test_canonical_app_registers_enterprise_routes():
    client = app.test_client()
    assert client.get("/operations").status_code == 200
    assert client.get("/analytics").status_code == 200
    assert client.get("/admin").status_code == 200
    assert client.get("/signup").status_code == 200
    assert client.get("/signin").status_code in {301, 302, 303, 307, 308}
    assert client.get("/api/enterprise/summary").status_code == 200
    assert client.get("/api/enterprise/health/detailed").status_code == 200

def test_canonical_route_map_contains_control_plane():
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    expected = {
        "/operations", "/analytics", "/admin", "/login", "/signup",
        "/api/enterprise/summary", "/api/enterprise/executions",
        "/api/enterprise/analytics/trends", "/api/enterprise/regressions",
        "/api/enterprise/baselines", "/api/enterprise/users",
    }
    assert expected.issubset(routes)
