from lib.services import TestRegistry


def test_default_registry_maps_all_validation_nodes():
    registry = TestRegistry.default()
    definitions = registry.definitions()

    assert len(definitions) == 11
    assert len({item.test_id for item in definitions}) == 11
    assert len({item.node_id for item in definitions}) == 11

    definition = registry.resolve(
        "tests/test_ping.py::test_latency_within_threshold"
    )
    assert definition.test_id == "wifi.latency.threshold"
    assert definition.metric_definitions["latency"] == "ms"
    assert definition.threshold_definitions["max_latency"] == "thresholds.max_latency_ms"


def test_registry_fallback_is_deterministic():
    registry = TestRegistry.default()

    first = registry.resolve_or_fallback(
        "tests/test_run_service.py::test_create_start_complete_run_lifecycle"
    )
    second = registry.resolve_or_fallback(
        "tests/test_run_service.py::test_create_start_complete_run_lifecycle"
    )

    assert first.test_id == second.test_id
    assert first.node_id == second.node_id
    assert first.category == "internal"
