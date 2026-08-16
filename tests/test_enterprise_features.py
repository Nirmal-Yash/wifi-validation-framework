from __future__ import annotations
import os
os.environ.setdefault("FLASK_TESTING", "1")
os.environ.setdefault("NETFORGE_AUTH_DISABLED", "1")
from dashboard.enterprise_app import app
from engine.execution_store import create_execution, get_execution, record_metric

def test_enterprise_summary_and_health():
    client=app.test_client()
    assert client.get("/api/enterprise/summary").status_code==200
    health=client.get("/api/enterprise/health/detailed")
    assert health.status_code==200
    assert health.get_json()["success"] is True

def test_regression_and_baseline_endpoints_are_real():
    eid=create_execution("feature-test","unit","pytest","tier1","","python -m pytest",["tests/","-m","not live"])
    record_metric(eid,"throughput_mbps",100.0,"Mbps")
    client=app.test_client()
    assert client.get("/api/enterprise/regressions").status_code==200
    assert client.get("/api/enterprise/baselines").status_code==200
    assert client.get(f"/api/enterprise/executions/{eid}/results").status_code==200
    assert get_execution(eid)["pytest_args_json"]

def test_execution_export_is_available():
    eid=create_execution("export-test","unit","pytest","tier1","","python -m pytest",["tests/"])
    response=app.test_client().get(f"/api/enterprise/export/execution/{eid}")
    assert response.status_code==200
    assert response.mimetype=="application/json"
