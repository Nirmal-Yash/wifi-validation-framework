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


def test_openapi_documents_structured_visual_topology_intent_and_provider_boundaries():
    content = SPEC.read_text(encoding="utf-8")
    topology = content.split("  /topologies/validate:", 1)[1].split("\n  /dashboard/operations-overview:", 1)[0]
    for field in (
        "vendor", "operating_system", "image", "cpu_cores", "memory_mb",
        "management_address", "default_gateway", "vlan_id",
        "configuration_profile_id", "credential_ref_id", "interfaces",
        "source_interface_name", "target_interface_name", "link_type",
        "network_segment_id",
    ):
        assert field in topology
    assert "Optional provider-specific template mapping" in topology
    assert "credential_ref_id is an opaque Credential Vault reference ID only" in topology
    assert "unmapped provider-independent logical node" in topology
    assert "Does not persist a revision or contact a provider" in topology
    assert "configuration_profile_id must identify a PUBLISHED profile" in topology
    assert "PUBLISHED profile backed by an ACTIVE schema" in topology
    assert "ACTIVE Vault record in the same Project" in topology
    assert '"404": {description: Project, selected profile, credential or configuration profile not found' in topology
    assert '"422": {description: Topology definition, interface or reference state' in topology

