from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from lib.domain import (
    Attempt,
    ConfigSnapshot,
    EnvironmentSnapshot,
    Run,
    RunLifecycle,
)
from .configuration import ConfigurationResolver, ResolvedConfiguration
from .environment_fingerprint import (
    EnvironmentFingerprint,
    EnvironmentFingerprintService,
)
from .resource_lock import ResourceLeaseGroup, ResourceLockManager
from .run_service import RunService, redact_configuration


@dataclass(frozen=True, slots=True)
class RunExecutionSession:
    run: Run
    attempt: Attempt
    configuration: ResolvedConfiguration
    fingerprint: EnvironmentFingerprint
    lease: ResourceLeaseGroup


_TERMINAL_STATES = {
    RunLifecycle.COMPLETED,
    RunLifecycle.FAILED,
    RunLifecycle.LAB_FAILED,
    RunLifecycle.CANCELLED,
    RunLifecycle.ABORTED,
}


class RunOrchestrator:
    def __init__(
        self,
        *,
        run_service: RunService,
        resolver: ConfigurationResolver,
        fingerprint_service: EnvironmentFingerprintService,
        lock_manager: ResourceLockManager,
        lab_controller=None,
    ) -> None:
        self.run_service = run_service
        self.resolver = resolver
        self.fingerprint_service = fingerprint_service
        self.lock_manager = lock_manager
        self.lab_controller = lab_controller

    def prepare(
        self,
        *,
        firmware_version,
        lab_id,
        validation_profile,
        selected_tests,
        test_definition_versions,
        defaults,
        environment=None,
        lab=None,
        device=None,
        run_overrides=None,
        test_overrides=None,
        repository_commit,
        device_identity=None,
        topology=None,
        source_run_id=None,
        project_id=None,
    ) -> RunExecutionSession:
        configuration = self.resolver.resolve(
            defaults=defaults,
            environment=environment,
            lab=lab,
            device=device,
            run=run_overrides,
            test_override=test_overrides,
        )
        if self.lab_controller is not None:
            # This is a read-only compatibility preflight; provisioning remains
            # an explicit operator action and is never triggered by pytest.
            self.lab_controller.validate_launcher()

        resources = [f"lab:{lab_id}"]
        configured_device = (device_identity or {}).get("device_id")
        if configured_device is None:
            configured_device = configuration.values.get("device_id")
        if configured_device:
            resources.append(f"device:{configured_device}")

        namespace_id = (
            (device_identity or {}).get("namespace_id")
            or (device_identity or {}).get("network_namespace")
            or configuration.values.get("namespace_id")
        )
        if namespace_id:
            resources.append(f"namespace:{namespace_id}")

        lease = self.lock_manager.acquire_many(
            resources,
            f"runner:{os.getpid()}:{self.run_service.id_generator()[-8:]}",
        )
        run = None
        try:
            run, attempt = self.run_service.create_run(
                firmware_version=firmware_version,
                lab_id=lab_id,
                validation_profile=validation_profile,
                selected_tests=selected_tests,
                test_definition_versions=test_definition_versions,
                resolved_config=redact_configuration(configuration.values),
                repository_commit=repository_commit,
                source_run_id=source_run_id,
                project_id=project_id,
            )
            run = self.run_service.transition(run.run_id, RunLifecycle.PREPARING)
            fingerprint = self.fingerprint_service.capture(
                lab_id=lab_id,
                configuration_hash=configuration.configuration_hash,
                topology=topology,
                device_identity=device_identity,
            )
            run.configuration_hash = configuration.configuration_hash
            run.config_snapshot = ConfigSnapshot(
                snapshot_id=self.run_service.id_generator(),
                resolved_config=redact_configuration(configuration.values),
                configuration_hash=configuration.configuration_hash,
            )
            run.environment = EnvironmentSnapshot(
                self.run_service.id_generator(),
                fingerprint.payload["host"]["os"],
                fingerprint.payload["host"]["kernel"],
                fingerprint.payload["host"]["python"],
                repository_commit,
                configuration.configuration_hash,
                {"fingerprint": fingerprint.fingerprint},
            )
            self.run_service.run_repository.update(run)
            return RunExecutionSession(
                run, attempt, configuration, fingerprint, lease
            )
        except Exception as exc:
            if run is not None:
                try:
                    current = self.run_service.run_repository.get(run.run_id)
                    if current is not None and current.lifecycle not in _TERMINAL_STATES:
                        self.run_service.lab_fail_run(
                            run.run_id, f"Run preparation failed: {exc}"
                        )
                except Exception:
                    pass
            lease.release()
            raise

    def finalize(
        self,
        session: RunExecutionSession,
        *,
        exitstatus: int = 0,
        finalizer: Callable[[str], Run] | None = None,
    ) -> Run:
        try:
            if finalizer is not None:
                return finalizer(session.run.run_id)
            if exitstatus == 0:
                return self.run_service.complete_run(session.run.run_id)
            if exitstatus == 2:
                return self.run_service.abort_run(session.run.run_id)
            return self.run_service.fail_run(
                session.run.run_id, failure_class=None
            )
        except Exception as exc:
            try:
                current = self.run_service.run_repository.get(session.run.run_id)
                if current is not None and current.lifecycle not in _TERMINAL_STATES:
                    self.run_service.worker_crashed(
                        session.run.run_id,
                        f"Run finalization failed: {exc}",
                    )
            except Exception:
                pass
            raise
        finally:
            session.lease.release()
