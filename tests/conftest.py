import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

# Bootstrap project root into sys.path before any local package imports
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
import yaml

from lib.connector import ConnectionPool, load_devices
from lib.adapters import DeviceProfile, OpenWrtDeviceAdapter, SSHFirmwareAdapter, VirtualLinuxDeviceAdapter
from lib.db_helper import init_db, insert_result
from lib.domain import (
    EnvironmentHealthStatus,
    EvidenceState,
    RunLifecycle,
    TelemetryEnvironmentClass,
    TestResultStatus,
)
from lib.repositories import SQLiteDatabase
from lib.services import (
    ArtifactService,
    CommandAuditRecorder,
    FaultService,
    ProtocolEvidenceService,
    LabHealthService,
    CommandSecurityPolicy,
    LocalRunner,
    MetricCollector,
    NetmikoRunner,
    RunContext,
    SecureCommandRunner,
    RunService,
    legacy_pool_adapter,
    TestRegistry,
    WifiTelemetryService,
    ConfigurationResolver,
    EnvironmentFingerprintService,
    ResourceLockManager,
    LabController,
    RunOrchestrator,
    repository_commit,
    redact_configuration,
)


def pytest_addoption(parser):
    parser.addoption(
        "--firmware-version",
        action="store",
        default="v1.0",
        help="Firmware version tag for this test run",
    )


@pytest.fixture(scope="session")
def firmware_version(request):
    return request.config.getoption("--firmware-version")


@pytest.fixture(scope="session")
def params():
    params_path = ROOT / "configs" / "test_params.yaml"
    if not params_path.exists():
        raise FileNotFoundError(f"Configuration file missing: {params_path}")
    with open(params_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def devices():
    return load_devices()


@pytest.fixture(scope="session")
def connection_pool(request):
    if os.getenv("NETREGRESS_CI_MODE","0").lower() in {"1","true","yes"}:
        pytest.skip("REAL_LAB connection fixture is disabled in hardware-free CI mode")
    context = getattr(request.config, "_netregress_run_context", None)
    if context is not None and isinstance(context.command_runner, SecureCommandRunner):
        yield legacy_pool_adapter(context.command_runner)
        return

    pool = ConnectionPool()
    yield pool
    pool.close_all()


class MetricLogger(MetricCollector):
    """Backward-compatible metric fixture with semantic policy-aware naming."""

    def __init__(self, node, default_name="metric"):
        super().__init__()
        self._node = node
        self._default_name = default_name

    def log(self, value, unit, **kwargs):
        if "name" not in kwargs:
            kwargs["name"] = self._default_name
        super().log(value, unit, **kwargs)
        try:
            val_float = float(value)
        except (ValueError, TypeError):
            val_float = None
        self._node.user_properties.append(("metric_value", val_float))
        self._node.user_properties.append(("metric_unit", str(unit)))


@pytest.fixture(autouse=True)
def lab_health_gate(request):
    if getattr(request.config, "_netregress_health_blocked", False):
        pytest.skip("Lab health failed before validation execution")


@pytest.fixture
def metric_logger(request):
    default_name = "metric"
    context = getattr(request.config, "_netregress_run_context", None)
    if context is not None:
        definition = context.definition_for(request.node.nodeid)
        policy_metrics = tuple(definition.measurement_policies)
        if len(policy_metrics) == 1:
            default_name = policy_metrics[0]
    collector = MetricLogger(request.node, default_name=default_name)
    request.node._metric_collector = collector
    return collector


@pytest.fixture(autouse=True)
def record_test_result(request, firmware_version):
    if os.getenv("NETREGRESS_CI_MODE","0").lower() in {"1","true","yes"}:
        yield
        return
    start_time = time.time()
    context = getattr(request.config, "_netregress_run_context", None)
    telemetry_before = None
    if context is not None and context.telemetry_service is not None and os.getenv("NETREGRESS_AUTO_TELEMETRY", "1") not in {"0", "false", "no"}:
        try:
            telemetry_before = context.telemetry_service.capture_and_register(
                run_id=context.run_id,
                artifact_service=context.artifact_service,
                interface=os.getenv("NETREGRESS_WIFI_INTERFACE", "wlan0"),
            )
        except Exception as exc:
            request.node.user_properties.append(("telemetry_before_warning", str(exc)))

    yield

    duration_ms = int((time.time() - start_time) * 1000)
    rep_call = getattr(request.node, "rep_call", None)
    rep_setup = getattr(request.node, "rep_setup", None)
    if rep_call is not None:
        status = "PASS" if rep_call.passed else "FAIL"
        error_message = str(rep_call.longrepr) if rep_call.failed else None
    elif rep_setup is not None and rep_setup.failed:
        status = "FAIL"
        error_message = f"Setup failed: {rep_setup.longrepr}"
    else:
        return

    if context is not None and context.telemetry_service is not None and os.getenv("NETREGRESS_AUTO_TELEMETRY", "1") not in {"0", "false", "no"}:
        try:
            context.telemetry_service.capture_and_register(
                run_id=context.run_id,
                artifact_service=context.artifact_service,
                interface=os.getenv("NETREGRESS_WIFI_INTERFACE", "wlan0"),
            )
        except Exception as exc:
            request.node.user_properties.append(("telemetry_after_warning", str(exc)))

    props = dict(request.node.user_properties)
    metric_val = props.get("metric_value")
    metric_unit = props.get("metric_unit")

    try:
        insert_result(
            test_name=request.node.nodeid,
            status=status,
            firmware_version=firmware_version,
            duration_ms=duration_ms,
            error_message=error_message,
            metric_value=metric_val,
            metric_unit=metric_unit,
        )
    except Exception as db_err:
        sys.stderr.write(f"\n[WARN] Failed to insert test result to DB: {db_err}\n")

    if context is not None:
        collector = getattr(request.node, "_metric_collector", None)
        metrics = collector.metrics() if collector is not None else ()
        definition = context.definition_for(request.node.nodeid)

        evidence_state = EvidenceState.NOT_REQUIRED
        if definition.evidence_requirements:
            evidence_state = EvidenceState.REQUIRED
            artifacts = context.artifact_service.list_for_run(context.run_id) if context.artifact_service else []
            by_type = {artifact.artifact_type for artifact in artifacts if artifact.test_result_id in {None, request.node.nodeid}}
            missing = [kind for kind in definition.evidence_requirements if kind not in by_type]
            invalid = False
            for artifact in artifacts:
                if artifact.artifact_type in definition.evidence_requirements and context.artifact_service is not None:
                    try:
                        if not context.artifact_service.verify(artifact.artifact_id):
                            invalid = True
                    except Exception:
                        invalid = True
            if invalid:
                evidence_state = EvidenceState.INVALID
            elif missing:
                evidence_state = EvidenceState.INCOMPLETE
            else:
                evidence_state = EvidenceState.COMPLETE
                if status == "PASS":
                    status = "PASS"

        result_status = (
            TestResultStatus.PASS if status == "PASS" else TestResultStatus.FAIL
        )
        if definition.evidence_requirements and evidence_state in {EvidenceState.INCOMPLETE, EvidenceState.INVALID} and result_status is TestResultStatus.PASS:
            result_status = TestResultStatus.UNVALIDATED
            error_message = error_message or f"required evidence state: {evidence_state.value}"

        context.run_service.record_test_result(
            run_id=context.run_id,
            attempt_id=context.attempt_id,
            test_id=definition.test_id,
            node_id=request.node.nodeid,
            test_version=definition.version,
            status=result_status,
            criticality=definition.criticality,
            severity=definition.severity,
            evidence_state=evidence_state,
            metrics=metrics,
            error_reason=error_message,
        )


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


def _validation_profile(config) -> str:
    markexpr = getattr(config.option, "markexpr", "") or ""
    if "smoke" in markexpr.lower():
        return "Smoke"
    if "perf" in markexpr.lower():
        return "Performance"
    if "regression" in markexpr.lower():
        return "Standard Regression"
    return os.getenv("NETREGRESS_VALIDATION_PROFILE", "Full")


def _create_run_service() -> RunService:
    db_path = Path(
        os.getenv("TEST_DB_PATH", str(ROOT / "results" / "test_results.db"))
    )
    return RunService.from_sqlite(SQLiteDatabase(db_path))


def _run_repository_context(session):
    return getattr(session.config, "_netregress_run_context", None)


@pytest.hookimpl(trylast=True)
def pytest_collection_finish(session):
    if not session.items or os.getenv("NETREGRESS_CI_MODE","0").lower() in {"1","true","yes"}:
        return

    params_path = ROOT / "configs" / "test_params.yaml"
    with open(params_path, "r", encoding="utf-8") as handle:
        params = yaml.safe_load(handle) or {}

    firmware_version = session.config.getoption("--firmware-version")
    selected_tests = [item.nodeid for item in session.items]
    registry = TestRegistry.default()
    test_versions = registry.version_map(selected_tests)
    resolver = ConfigurationResolver()
    resolved = resolver.resolve(defaults=params, environment=resolver.environment_json())
    persisted_config = redact_configuration(resolved.values)

    service = _create_run_service()
    lock_manager = ResourceLockManager(ROOT / "results" / "locks")
    fingerprint_service = EnvironmentFingerprintService(ROOT)
    lab_controller = LabController(
        command_runner=LocalRunner(),
        provisioning_script=ROOT / "wifi_lab_reprovision_robust.sh",
        lab_id=os.getenv("NETREGRESS_LAB_ID", "WiFi-Regression-Lab"),
    )
    orchestrator = RunOrchestrator(
        run_service=service,
        resolver=resolver,
        fingerprint_service=fingerprint_service,
        lock_manager=lock_manager,
        lab_controller=lab_controller,
    )
    orchestration = orchestrator.prepare(
        firmware_version=firmware_version,
        lab_id=os.getenv("NETREGRESS_LAB_ID", "WiFi-Regression-Lab"),
        validation_profile=_validation_profile(session.config),
        selected_tests=selected_tests,
        test_definition_versions=test_versions,
        defaults=params,
        environment=resolver.environment_json(),
        repository_commit=os.getenv("NETREGRESS_REPOSITORY_COMMIT")
        or repository_commit(str(ROOT)),
        device_identity={"device_id": os.getenv("NETREGRESS_DEVICE_ID", "client_vm")},
        topology=params.get("network", {}),
    )
    run, attempt = orchestration.run, orchestration.attempt
    session.config._netregress_resource_lease = orchestration.lease
    session.config._netregress_environment_fingerprint = orchestration.fingerprint
    service.begin_lab_health_check(run.run_id)
    artifact_service = ArtifactService.from_sqlite(service.run_repository.database)
    audit_recorder = CommandAuditRecorder(
        artifact_service=artifact_service,
        event_repository=service.event_repository,
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        directory=ROOT / "results" / "command_logs",
    )
    command_runner = SecureCommandRunner(
        NetmikoRunner(ConnectionPool()),
        security_policy=CommandSecurityPolicy.compatibility(),
        audit_recorder=audit_recorder,
    )
    local_runner = SecureCommandRunner(
        LocalRunner(),
        security_policy=CommandSecurityPolicy.default(),
    )
    fault_service = FaultService(command_runner)
    protocol_evidence_service = ProtocolEvidenceService()
    telemetry_environment = TelemetryEnvironmentClass(
        os.getenv("NETREGRESS_WIFI_ENVIRONMENT_CLASS", "VIRTUAL_WIFI").upper()
    )
    device_id = os.getenv("NETREGRESS_DEVICE_ID", "client_vm")
    configured_devices = load_devices()
    if device_id not in configured_devices:
        raise RuntimeError(f"Configured device is missing from devices.yaml: {device_id}")
    device_profile = DeviceProfile.from_mapping(device_id, configured_devices[device_id])
    device_adapter = (
        OpenWrtDeviceAdapter.from_profile(device_profile, command_runner)
        if device_profile.device_type.lower() == "openwrt"
        else VirtualLinuxDeviceAdapter.from_profile(device_profile, command_runner)
    )
    firmware_adapter = SSHFirmwareAdapter(device_adapter)

    telemetry_service = WifiTelemetryService(
        command_runner=command_runner,
        target=os.getenv("NETREGRESS_DEVICE_ID", "client_vm"),
        environment_class=telemetry_environment,
        output_directory=ROOT / "results" / "telemetry",
    )
    session.config._netregress_run_context = RunContext(
        run_service=service,
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        lab_id=run.lab_id,
        device_id=os.getenv("NETREGRESS_DEVICE_ID", "client_vm"),
        resolved_config=persisted_config,
        test_registry=registry,
        artifact_service=artifact_service,
        command_runner=command_runner,
        fault_service=fault_service,
        protocol_evidence_service=protocol_evidence_service,
        telemetry_service=telemetry_service,
        device_adapter=device_adapter,
        firmware_adapter=firmware_adapter,
        lab_controller=lab_controller,
        configuration_hash=resolved.configuration_hash,
        configuration_provenance=resolved.provenance,
        environment_fingerprint=orchestration.fingerprint.fingerprint,
        logger=logging.getLogger("netregress"),
    )

    health_service = LabHealthService(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        local_runner=local_runner,
        remote_runner=command_runner,
        artifact_service=artifact_service,
        event_repository=service.event_repository,
        output_directory=ROOT / "results" / "lab-health",
        resolved_config=persisted_config,
        gns3_api=os.getenv("GNS3_API", "http://127.0.0.1:3080"),
        gns3_project_name=os.getenv("GNS3_PROJECT_NAME", "WiFi-Regression-Lab"),
    )
    session.config._netregress_health_service = health_service
    session.config._netregress_local_health_runner = local_runner
    try:
        pre_health = health_service.check(phase="BEFORE")
        service.record_environment_health(run.run_id, pre_health.overall_status)
        health_failed = pre_health.overall_status == EnvironmentHealthStatus.FAILED
    except Exception as exc:
        sys.stderr.write(f"\n[ERROR] Pre-run lab health evaluation failed: {exc}\n")
        service.lab_fail_run(run.run_id)
        health_failed = True
    session.config._netregress_health_blocked = health_failed
    if not session.config._netregress_health_blocked:
        started_run = service.start_run_after_health(run.run_id)
        started_run.execution_pid = os.getpid()
        service.run_repository.update(started_run)


def pytest_sessionfinish(session, exitstatus):
    context = getattr(session.config, "_netregress_run_context", None)
    if context is None:
        return

    run = context.run_service.run_repository.get(context.run_id)
    health_error = None
    runner_error = None

    if run is not None and run.lifecycle not in {
        RunLifecycle.COMPLETED,
        RunLifecycle.FAILED,
        RunLifecycle.LAB_FAILED,
        RunLifecycle.CANCELLED,
        RunLifecycle.ABORTED,
    }:
        try:
            health_service = getattr(session.config, "_netregress_health_service", None)
            if health_service is not None:
                post_health = health_service.check(phase="AFTER")
                context.run_service.record_environment_health(
                    context.run_id,
                    post_health.overall_status,
                )
                if post_health.overall_status == EnvironmentHealthStatus.FAILED:
                    context.run_service.lab_fail_run(context.run_id)
                    health_error = "post-run lab health failed"
        except Exception as exc:
            health_error = str(exc)
            context.run_service.lab_fail_run(context.run_id)

    close = getattr(context.command_runner, "close", None)
    if close is not None:
        try:
            close()
        except Exception as exc:
            runner_error = exc
            sys.stderr.write(
                f"\n[ERROR] Command execution audit finalization failed: {exc}\n"
            )

    local_health_runner = getattr(session.config, "_netregress_local_health_runner", None)
    local_close = getattr(local_health_runner, "close", None)
    if local_close is not None:
        try:
            local_close()
        except Exception as exc:
            runner_error = runner_error or exc

    run = context.run_service.run_repository.get(context.run_id)
    if run is not None and run.lifecycle not in {
        RunLifecycle.COMPLETED,
        RunLifecycle.FAILED,
        RunLifecycle.LAB_FAILED,
        RunLifecycle.CANCELLED,
        RunLifecycle.ABORTED,
    }:
        if runner_error is not None or health_error is not None:
            context.run_service.lab_fail_run(context.run_id)
        elif exitstatus == 0:
            context.run_service.complete_run(context.run_id)
        elif exitstatus == 2:
            context.run_service.abort_run(context.run_id)
        else:
            context.run_service.fail_run(context.run_id)

    lease = getattr(session.config, "_netregress_resource_lease", None)
    if lease is not None:
        try: lease.release()
        except Exception as exc: sys.stderr.write(f"\n[WARN] Failed to release lab resource lock: {exc}\n")

    terminal = context.run_service.run_repository.get(context.run_id)
    if terminal is not None:
        try:
            from lib.services import DiagnosticBundleService, ReproductionManifestService
            DiagnosticBundleService(
                artifact_service=context.artifact_service,
                results_root=ROOT / "results",
            ).build(
                run_id=context.run_id,
                reason=(terminal.failure_reason or terminal.failure_class.value if terminal.failure_class else "terminal-run-record"),
            ) if terminal.lifecycle is not RunLifecycle.COMPLETED else None
            ReproductionManifestService(
                test_registry=context.test_registry,
                root=ROOT,
            ).create(context.run_id, terminal)
        except Exception as exc:
            sys.stderr.write(f"\n[WARN] Failed to finalize diagnostic/reproduction evidence: {exc}\n")

    try:
        from lib.services import RunnerSyncService
        RunnerSyncService.from_sqlite(
            context.run_service.run_repository.database,
            runner_id=os.getenv("NETREGRESS_RUNNER_ID", os.getenv("HOSTNAME", "local-runner")),
        ).queue_run(context.run_id)
    except Exception as exc:
        sys.stderr.write(f"\n[WARN] Failed to queue Run for synchronization: {exc}\n")


@pytest.fixture(scope="session")
def run_context(request):
    return getattr(request.config, "_netregress_run_context", None)


@pytest.fixture
def fault_service(run_context):
    assert run_context is not None
    assert run_context.fault_service is not None
    return run_context.fault_service


@pytest.fixture
def device_adapter(run_context):
    assert run_context is not None
    assert run_context.device_adapter is not None
    return run_context.device_adapter


@pytest.fixture
def firmware_adapter(run_context):
    assert run_context is not None
    assert run_context.firmware_adapter is not None
    return run_context.firmware_adapter


@pytest.fixture
def telemetry_service(run_context):
    assert run_context is not None
    assert run_context.telemetry_service is not None
    return run_context.telemetry_service
