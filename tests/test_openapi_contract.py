from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "openapi.yaml"


def test_openapi_path_keys_are_unique_and_cover_runtime_routes():
    content = SPEC.read_text(encoding="utf-8")
    paths = re.findall(r"^  (/[^\n:]+):", content, flags=re.MULTILINE)
    assert len(paths) == len(set(paths)), "duplicate OpenAPI path key"
    assert {"/auth/activity", "/readiness", "/runs/{run_id}/release-gate", "/waivers", "/sync/queue", "/firmware/{device_id}/rollback"} <= set(paths)


def test_openapi_auth_cookie_and_runtime_protection_match_flask():
    content = SPEC.read_text(encoding="utf-8")
    assert "name: netregress_session" in content
    assert "/readiness: {get: {responses:" in content
    assert "/auth/activity:" in content and "expected_version" in content
    assert "/waivers:\n    get:" in content
