from lib.services import CommandSecurityPolicy, LocalRunner, RunContext, SecureCommandRunner, TestRegistry


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
        command_runner=LocalRunner(),
    )

    definition = context.definition_for(
        "tests/test_dns.py::test_dns_resolution"
    )
    assert definition.test_id == "wifi.dns.resolution"
    assert definition.requires == ("wifi.dhcp.lease",)
    assert context.artifact_service is None


def test_run_context_carries_typed_command_runner():
    registry = TestRegistry.default()
    runner = LocalRunner()
    context = RunContext(
        run_service=object(),
        run_id="run-1",
        attempt_id="attempt-1",
        lab_id="lab-1",
        device_id="client_vm",
        resolved_config={},
        test_registry=registry,
        command_runner=runner,
    )

    assert context.command_runner is runner


def test_run_context_accepts_secure_command_runner():
    registry = TestRegistry.default()
    runner = SecureCommandRunner(
        LocalRunner(), security_policy=CommandSecurityPolicy.default()
    )
    context = RunContext(
        run_service=object(),
        run_id="run-1",
        attempt_id="attempt-1",
        lab_id="lab-1",
        device_id="client_vm",
        resolved_config={},
        test_registry=registry,
        command_runner=runner,
    )

    assert context.command_runner is runner
