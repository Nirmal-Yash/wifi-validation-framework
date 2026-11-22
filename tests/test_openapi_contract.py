from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "openapi.yaml"


def test_openapi_path_keys_are_unique_and_cover_runtime_routes():
    content = SPEC.read_text(encoding="utf-8")
    paths = re.findall(r"^  (/[^\n:]+):", content, flags=re.MULTILINE)
    assert len(paths) == len(set(paths)), "duplicate OpenAPI path key"
    assert {"/auth/activity", "/readiness", "/runs/{run_id}/release-gate", "/waivers", "/sync/queue", "/firmware/{device_id}/rollback", "/topologies/validate", "/dashboard/operations-overview"} <= set(paths)


def test_openapi_auth_cookie_and_runtime_protection_match_flask():
    content = SPEC.read_text(encoding="utf-8")
    assert "name: netregress_session" in content
    assert "/readiness: {get: {responses:" in content
    assert "/auth/activity:" in content and "expected_version" in content
    assert "/waivers:\n    get:" in content


def test_openapi_documents_operations_overview_scope_permissions_and_sections():
    content = SPEC.read_text(encoding="utf-8")
    overview = content.split("  /dashboard/operations-overview:", 1)[1].split("\n  /health:", 1)[0]
    assert "operationId: getOperationsOverview" in overview
    assert "name: project_id" in overview and "required: true" in overview
    assert "name: lab_id" in overview and "required: false" in overview
    for permission in (
        "workspace.read", "devices.read", "topology.read", "pipelines.read",
        "runs.read", "configurations.read", "evidence.read", "performance.read",
    ):
        assert permission in overview
    for section in (
        "network_health", "action_items", "performance", "configuration", "evidence",
    ):
        assert section in overview
    for status in ('"400":', '"401":', '"403":', '"404":'):
        assert status in overview
