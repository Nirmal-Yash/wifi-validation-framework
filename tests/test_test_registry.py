from lib.services import TestRegistry


def test_default_registry_maps_all_validation_nodes():
    registry = TestRegistry.default()
    definitions = registry.definitions()

    assert len(definitions) == 18
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


def test_performance_definitions_declare_decision_metric_policies():
    registry = TestRegistry.default()

    performance = [
        definition
        for definition in registry.definitions()
        if definition.category == "Performance"
    ]

    assert performance
    for definition in performance:
        assert definition.decision_metric in definition.metric_definitions
        assert definition.decision_metric in definition.measurement_policies
        metric_definition = registry.decision_metric_definition(definition.test_id)
        assert metric_definition is not None
        assert metric_definition.authoritative is True


def test_latency_decision_policy_uses_p95():
    registry = TestRegistry.default()

    definition = registry.get("wifi.latency.threshold")

    assert definition.decision_metric == "latency"
    assert definition.measurement_policies["latency"].aggregate.value == "p95"


def test_recovery_definitions_are_destructive_and_have_fault_metrics():
    registry = TestRegistry.default()

    recovery = [
        definition
        for definition in registry.definitions()
        if definition.category == "Recovery"
    ]

    assert len(recovery) == 8
    assert all(definition.destructive for definition in recovery)
    assert all("fault_observed" in definition.metric_definitions for definition in recovery)
    assert all("recovery_time" in definition.metric_definitions for definition in recovery)
