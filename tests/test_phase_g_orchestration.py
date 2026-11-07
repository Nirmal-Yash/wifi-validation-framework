from __future__ import annotations

import pytest

from lib.repositories import SQLiteDatabase
from lib.services import (
    ConfigurationResolver,
    EnvironmentFingerprintService,
    FirmwareOperationService,
    ResourceLockError,
    ResourceLockManager,
    RunOrchestrator,
    RunService,
)


class FakeLabController:
    def __init__(self, *, error=None):
        self.error = error
        self.validated = 0
        self.provisioned = 0

    def validate_launcher(self):
        self.validated += 1
        if self.error:
            raise self.error

    def provision(self, *args, **kwargs):
        self.provisioned += 1
        raise AssertionError("Run preflight must not provision the physical lab")


def _build(tmp_path, *, lab_controller=None):
    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    database = SQLiteDatabase(results / "test_results.db")
    service = RunService.from_sqlite(database)
    lock_manager = ResourceLockManager(results / "locks")
    orchestrator = RunOrchestrator(
        run_service=service,
        resolver=ConfigurationResolver(),
        fingerprint_service=EnvironmentFingerprintService(tmp_path),
        lock_manager=lock_manager,
        lab_controller=lab_controller,
    )
    return service, lock_manager, orchestrator, database


def _prepare(orchestrator, *, device_id="client_vm"):
    return orchestrator.prepare(
        firmware_version="v1.0",
        lab_id="lab-g",
        validation_profile="Smoke",
        selected_tests=["tests/test_ping.py::test_ping"],
        test_definition_versions={"tests/test_ping.py::test_ping": "1.0"},
        defaults={},
        device_identity={"device_id": device_id},
        repository_commit="test-commit",
    )


def test_orchestrator_preflights_launcher_without_mutating_lab(tmp_path):
    controller = FakeLabController()
    service, _, orchestrator, _ = _build(tmp_path, lab_controller=controller)

    session = _prepare(orchestrator)

    assert controller.validated == 1
    assert controller.provisioned == 0
    orchestrator.finalize(session, exitstatus=2)
    assert service.run_repository.get(session.run.run_id).lifecycle.value == "ABORTED"


def test_failed_lab_preflight_creates_no_run_or_lock(tmp_path):
    controller = FakeLabController(error=RuntimeError("launcher missing"))
    service, manager, orchestrator, _ = _build(tmp_path, lab_controller=controller)

    with pytest.raises(RuntimeError, match="launcher missing"):
        _prepare(orchestrator)

    assert service.run_repository.list() == []
    lease = manager.acquire("lab:lab-g", "next-owner")
    lease.release()


def test_validation_run_excludes_concurrent_firmware_operation(tmp_path):
    service, manager, orchestrator, database = _build(tmp_path)
    firmware = FirmwareOperationService(run_repository=service.run_repository)
    assert firmware.resource_lock_manager.directory == manager.directory

    session = _prepare(orchestrator, device_id="ap-01")
    with pytest.raises(ResourceLockError):
        firmware._acquire_lock("ap-01", session.run.run_id, "operator")

    orchestrator.finalize(session, exitstatus=2)
    firmware_lease = firmware._acquire_lock("ap-01", session.run.run_id, "operator")
    assert firmware_lease.active
    firmware_lease.release()


def test_orchestrator_acquires_lab_and_device_leases_atomically(tmp_path):
    _, manager, orchestrator, _ = _build(tmp_path)
    occupied = manager.acquire("lab:lab-g", "other-run")
    try:
        with pytest.raises(ResourceLockError):
            _prepare(orchestrator, device_id="ap-01")
        # The device lock is acquired first and must roll back when lab lock fails.
        device_lease = manager.acquire("device:ap-01", "next-run")
        device_lease.release()
    finally:
        occupied.release()


def test_orchestrator_also_excludes_a_shared_network_namespace(tmp_path):
    _, manager, orchestrator, _ = _build(tmp_path)
    session = orchestrator.prepare(
        firmware_version="v1.0",
        lab_id="lab-g",
        validation_profile="Smoke",
        selected_tests=["tests/test_ping.py::test_ping"],
        test_definition_versions={"tests/test_ping.py::test_ping": "1.0"},
        defaults={},
        device_identity={"device_id": "client-vm", "namespace_id": "netns-client"},
        repository_commit="test-commit",
    )
    with pytest.raises(ResourceLockError):
        manager.acquire("namespace:netns-client", "other-run")
    orchestrator.finalize(session, exitstatus=2)
    namespace_lease = manager.acquire("namespace:netns-client", "other-run")
    namespace_lease.release()
