from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from lib.domain import DomainValidationError, RunLifecycle
from lib.repositories import SQLiteDatabase
from lib.services import (
    ProcessNotManagedError,
    ProcessOwnershipError,
    RunProcessManager,
    RunService,
)


def _wait_for_log(path: str, marker: str = "worker-ready") -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if Path(path).is_file() and marker in Path(path).read_text(encoding="utf-8"):
            return
        time.sleep(0.01)
    raise AssertionError(f"worker did not write {marker!r} to {path}")


def _start_sleep(manager: RunProcessManager, *, ignore_term: bool = False):
    code = (
        "import signal,time; "
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN); " if ignore_term else "")
        + "print('worker-ready', flush=True); time.sleep(30)"
    )
    return manager._start_command([sys.executable, "-c", code])


def test_process_manager_captures_output_and_cancels_owned_group(tmp_path):
    manager = RunProcessManager(tmp_path)
    handle = _start_sleep(manager)
    manifest = manager._manifest_path(handle.pid)
    _wait_for_log(handle.log_path)

    assert manager.validate(handle.pid) is True
    assert manifest.is_file()
    record = json.loads(manifest.read_text(encoding="utf-8"))
    assert record["pid"] == handle.pid
    assert record["process_group"] == handle.pid
    assert record["session_id"] == handle.pid

    assert manager.cancel(handle.pid, grace_seconds=2, kill_timeout=2) is True
    assert not manifest.exists()
    assert "worker-ready" in Path(handle.log_path).read_text(encoding="utf-8")


def test_process_manager_escalates_when_sigterm_is_ignored(tmp_path):
    manager = RunProcessManager(tmp_path)
    handle = _start_sleep(manager, ignore_term=True)
    _wait_for_log(handle.log_path)

    assert manager.cancel(handle.pid, grace_seconds=0.1, kill_timeout=2) is True
    assert not manager._manifest_path(handle.pid).exists()


def test_process_manager_refuses_to_signal_unmanaged_pid(tmp_path):
    manager = RunProcessManager(tmp_path)

    with pytest.raises(ProcessNotManagedError):
        manager.cancel(os.getpid())


def test_process_manager_refuses_pid_identity_mismatch(tmp_path):
    manager = RunProcessManager(tmp_path)
    handle = _start_sleep(manager)
    _wait_for_log(handle.log_path)
    path = manager._manifest_path(handle.pid)
    _wait_for_log(handle.log_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["start_ticks"] += 1
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ProcessOwnershipError, match="reused"):
        manager.cancel(handle.pid, grace_seconds=0.1, kill_timeout=0.1)

    # A failed identity check must leave the actual worker running.
    assert RunProcessManager._read_proc_stat(handle.pid) is not None
    manifest["start_ticks"] -= 1
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert manager.cancel(handle.pid, grace_seconds=2, kill_timeout=2) is True


def test_process_manager_spawn_failure_leaves_no_manifest(tmp_path):
    manager = RunProcessManager(tmp_path)

    with pytest.raises(FileNotFoundError):
        manager._start_command([str(tmp_path / "missing-executable")])

    assert list((tmp_path / "results" / "processes").glob("*.json")) == []


def test_process_manager_rejects_empty_command(tmp_path):
    manager = RunProcessManager(tmp_path)

    with pytest.raises(ValueError, match="must not be empty"):
        manager._start_command([])


def test_run_service_persists_cancellation_intent_before_final_state(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "cancel-intent.sqlite"))
    run, _ = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Smoke",
        selected_tests=["tests/test_ping.py::test_ping"],
        test_definition_versions={"tests/test_ping.py::test_ping": "1.0"},
        resolved_config={},
        repository_commit="test-commit",
    )

    service.request_cancel(run.run_id, actor="test-operator", reason="test cancellation")

    assert service.cancellation_requested(run.run_id) is True
    events = service.event_repository.list_for_run(run.run_id)
    request = next(event for event in events if event.event_type == "RUN_CANCEL_REQUESTED")
    assert request.details == {
        "actor": "test-operator",
        "reason": "test cancellation",
    }

    cancelled = service.cancel_run(run.run_id, actor="test-operator", reason="test cancellation")
    assert cancelled.lifecycle is RunLifecycle.CANCELLED
    assert cancelled.failure_reason == "test-operator: test cancellation"


def test_run_service_rejects_cancel_intent_after_terminal_state(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "cancel-terminal.sqlite"))
    run, _ = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Smoke",
        selected_tests=["tests/test_ping.py::test_ping"],
        test_definition_versions={"tests/test_ping.py::test_ping": "1.0"},
        resolved_config={},
        repository_commit="test-commit",
    )
    service.cancel_run(run.run_id)

    with pytest.raises(DomainValidationError, match="terminal Run"):
        service.request_cancel(run.run_id)


def _make_orchestrator(tmp_path, *, fingerprint_service=None):
    from lib.services import (
        ConfigurationResolver,
        EnvironmentFingerprintService,
        ResourceLockManager,
        RunOrchestrator,
    )

    database = SQLiteDatabase(tmp_path / "orchestrator.sqlite")
    service = RunService.from_sqlite(database)
    manager = ResourceLockManager(tmp_path / "locks")
    orchestrator = RunOrchestrator(
        run_service=service,
        resolver=ConfigurationResolver(),
        fingerprint_service=fingerprint_service or EnvironmentFingerprintService(tmp_path),
        lock_manager=manager,
    )
    return orchestrator, service, manager


def _prepare(orchestrator):
    return orchestrator.prepare(
        firmware_version="v1.0",
        lab_id="lab-f",
        validation_profile="Smoke",
        selected_tests=["tests/test_ping.py::test_ping"],
        test_definition_versions={"tests/test_ping.py::test_ping": "1.0"},
        defaults={},
        repository_commit="test-commit",
    )


def test_orchestrator_marks_prepare_failure_and_releases_lab_lease(tmp_path):
    class FailingFingerprint:
        def capture(self, **kwargs):
            raise RuntimeError("fingerprint unavailable")

    orchestrator, service, manager = _make_orchestrator(
        tmp_path, fingerprint_service=FailingFingerprint()
    )

    with pytest.raises(RuntimeError, match="fingerprint unavailable"):
        _prepare(orchestrator)

    runs = service.run_repository.list()
    assert len(runs) == 1
    assert runs[0].lifecycle is RunLifecycle.LAB_FAILED

    lease = manager.acquire("lab:lab-f", "next-owner")
    lease.release()


def test_orchestrator_finalizer_failure_marks_worker_crash_and_releases_lease(tmp_path):
    orchestrator, service, manager = _make_orchestrator(tmp_path)
    session = _prepare(orchestrator)

    def fail_finalizer(_run_id):
        raise RuntimeError("finalizer exploded")

    with pytest.raises(RuntimeError, match="finalizer exploded"):
        orchestrator.finalize(session, finalizer=fail_finalizer)

    stored = service.run_repository.get(session.run.run_id)
    assert stored.lifecycle is RunLifecycle.ABORTED
    assert stored.failure_class.value == "WORKER_CRASHED"

    lease = manager.acquire("lab:lab-f", "next-owner")
    lease.release()


def test_process_manager_force_kill_is_owned_and_reaped(tmp_path):
    manager = RunProcessManager(tmp_path)
    handle = _start_sleep(manager)
    _wait_for_log(handle.log_path)

    assert manager.kill(handle.pid, timeout=2) is True
    assert not manager._manifest_path(handle.pid).exists()


def test_timeout_classification_is_infrastructure_not_product_failure(tmp_path):
    from lib.domain import EnvironmentHealthStatus, FailureClass

    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "timeout.sqlite"))
    run, _ = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Smoke",
        selected_tests=["tests/test_ping.py::test_ping"],
        test_definition_versions={"tests/test_ping.py::test_ping": "1.0"},
        resolved_config={},
        repository_commit="test-commit",
    )
    service.begin_lab_health_check(run.run_id)
    service.record_environment_health(run.run_id, EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(run.run_id)

    timed_out = service.timeout_run(run.run_id, "worker exceeded timeout")
    assert timed_out.lifecycle is RunLifecycle.ABORTED
    assert timed_out.failure_class is FailureClass.TIMED_OUT
    assert timed_out.outcome.value == "UNVALIDATED"
