from lib.services import RunContext, TestRegistry


def test_run_context_exposes_semantic_definition():
    registry = TestRegistry.default()

    context = RunContext(
        run_service=object(),
        run_id="run-1",
        attempt_id="attempt-1",
        lab_id="lab-1",
        device_id="client_vm",
        resolved_config={"wifi": {"ssid": "Test"}},
        test_registry=registry,
    )

    definition = context.definition_for(
        "tests/test_dns.py::test_dns_resolution"
    )
    assert definition.test_id == "wifi.dns.resolution"
    assert definition.requires == ("wifi.dhcp.lease",)
    assert context.artifact_service is None
