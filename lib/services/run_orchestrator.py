from __future__ import annotations
from dataclasses import dataclass
import os
from typing import Callable
from lib.domain import Attempt,EnvironmentSnapshot,Run
from .configuration import ConfigurationResolver,ResolvedConfiguration
from .environment_fingerprint import EnvironmentFingerprint,EnvironmentFingerprintService
from .resource_lock import ResourceLease,ResourceLockManager
from .run_service import RunService,redact_configuration
@dataclass(frozen=True,slots=True)
class RunExecutionSession: run:Run; attempt:Attempt; configuration:ResolvedConfiguration; fingerprint:EnvironmentFingerprint; lease:ResourceLease
class RunOrchestrator:
    def __init__(self,*,run_service,resolver,fingerprint_service,lock_manager,lab_controller=None): self.run_service=run_service; self.resolver=resolver; self.fingerprint_service=fingerprint_service; self.lock_manager=lock_manager; self.lab_controller=lab_controller
    def prepare(self,*,firmware_version,lab_id,validation_profile,selected_tests,test_definition_versions,defaults,environment=None,lab=None,device=None,run_overrides=None,test_overrides=None,repository_commit,device_identity=None,topology=None):
        configuration=self.resolver.resolve(defaults=defaults,environment=environment,lab=lab,device=device,run=run_overrides,test_override=test_overrides)
        lease=self.lock_manager.acquire(f"lab:{lab_id}",f"runner:{os.getpid()}:{self.run_service.id_generator()[-8:]}")
        try:
            run,attempt=self.run_service.create_run(firmware_version=firmware_version,lab_id=lab_id,validation_profile=validation_profile,selected_tests=selected_tests,test_definition_versions=test_definition_versions,resolved_config=redact_configuration(configuration.values),repository_commit=repository_commit)
            fp=self.fingerprint_service.capture(lab_id=lab_id,configuration_hash=configuration.configuration_hash,topology=topology,device_identity=device_identity)
            run.configuration_hash=configuration.configuration_hash
            run.environment=EnvironmentSnapshot(self.run_service.id_generator(),fp.payload["host"]["os"],fp.payload["host"]["kernel"],fp.payload["host"]["python"],repository_commit,configuration.configuration_hash,{"fingerprint":fp.fingerprint})
            self.run_service.run_repository.update(run)
            return RunExecutionSession(run,attempt,configuration,fp,lease)
        except Exception:
            lease.release(); raise
    def finalize(self,session,*,exitstatus=0,finalizer:Callable[[str],Run]|None=None):
        try:
            if finalizer:return finalizer(session.run.run_id)
            return self.run_service.complete_run(session.run.run_id) if exitstatus==0 else self.run_service.abort_run(session.run.run_id) if exitstatus==2 else self.run_service.fail_run(session.run.run_id)
        finally: session.lease.release()
