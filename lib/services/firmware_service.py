from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from lib.domain import ArtifactType, LifecycleEvent
from lib.repositories import EventRepository, RunRepository
from .artifact_service import ArtifactService
from .run_service import generate_ulid
from lib.adapters.firmware import FirmwareAdapter, FirmwareAuthorization, FirmwareError, FirmwareImage, FirmwareOperationResult, FirmwareValidationError

class FirmwareOperationService:
    def __init__(self, *, run_repository: RunRepository | None = None, event_repository: EventRepository | None = None, artifact_service: ArtifactService | None = None, id_generator=generate_ulid):
        self.run_repository=run_repository; self.event_repository=event_repository; self.artifact_service=artifact_service; self.id_generator=id_generator

    def update(self, *, adapter: FirmwareAdapter, image: FirmwareImage, authorization: FirmwareAuthorization, run_id: str | None = None):
        authorization.require('FLASH')
        identity=adapter.identify()
        self._event(run_id,'FIRMWARE_IDENTIFIED',{'device_id':identity.device_id,'version':identity.firmware_version})
        validation=adapter.validate_image(image)
        self._event(run_id,'FIRMWARE_VALIDATED',{'valid':validation.valid,'sha256':validation.sha256,'version':validation.image_version,'reasons':list(validation.reasons)})
        if not validation.valid: raise FirmwareValidationError('; '.join(validation.reasons) or 'firmware image failed validation')
        if run_id and self.artifact_service is not None:
            self.artifact_service.register_file(run_id=run_id,path=image.path,artifact_type=ArtifactType.FIRMWARE_REFERENCE,display_name=f'firmware-{image.version}-{Path(image.path).name}',sensitivity_class='SENSITIVE',expected_sha256=validation.sha256)
        auth=lambda op: FirmwareAuthorization(authorization.actor, authorization.reason, True, op)
        try:
            remote=adapter.upload(image,authorization=auth('UPLOAD'))
            self._event(run_id,'FIRMWARE_UPLOADED',{'remote_path':remote})
        except Exception as exc:
            self._event(run_id,'FIRMWARE_UPLOAD_FAILED',{'error':str(exc)}); raise
        try:
            self._event(run_id,'FIRMWARE_PREPARING',{'remote_path':remote})
            prepared=adapter.prepare(remote,image,authorization=auth('PREPARE'))
            if prepared.transport_error or prepared.exit_code not in (None,0): raise FirmwareError('firmware preparation failed')
            self._event(run_id,'FIRMWARE_PREPARED',{'remote_path':remote})
        except Exception as exc:
            self._event(run_id,'FIRMWARE_PREPARE_FAILED',{'error':str(exc)}); raise
        try:
            self._event(run_id,'FIRMWARE_FLASHING',{'remote_path':remote})
            flashed=adapter.flash(remote,image,authorization=auth('FLASH'))
            if flashed.transport_error or flashed.exit_code not in (None,0): raise FirmwareError('firmware flash failed; automatic retry and rollback are disabled')
            self._event(run_id,'FIRMWARE_FLASH_COMPLETED',{'remote_path':remote})
        except Exception as exc:
            self._event(run_id,'FIRMWARE_FLASH_FAILED',{'error':str(exc)}); raise
        try:
            self._event(run_id,'FIRMWARE_REBOOTING',{})
            rebooted=adapter.reboot(authorization=auth('REBOOT'))
            if rebooted.transport_error or rebooted.exit_code not in (None,0): raise FirmwareError('device reboot failed; rollback requires a separate explicit operation')
            self._event(run_id,'FIRMWARE_REBOOT_COMPLETED',{})
        except Exception as exc:
            self._event(run_id,'FIRMWARE_REBOOT_FAILED',{'error':str(exc)}); raise
        try:
            ready=adapter.wait_ready(); self._event(run_id,'FIRMWARE_READY',{'version':ready.firmware_version})
            verified=adapter.verify_version(image.version); self._event(run_id,'FIRMWARE_VERSION_VERIFIED',{'version':verified.firmware_version})
        except Exception as exc:
            self._event(run_id,'FIRMWARE_VERSION_VERIFICATION_FAILED',{'error':str(exc)}); raise
        return FirmwareOperationResult('UPDATE',verified.device_id,image.version,'VERSION_VERIFIED',verified.firmware_version,remote,validation)

    def rollback(self, *, adapter: FirmwareAdapter, authorization: FirmwareAuthorization, run_id: str | None = None):
        authorization.require('ROLLBACK')
        try:
            self._event(run_id,'FIRMWARE_ROLLBACK_STARTED',{})
            result=adapter.rollback(authorization=authorization)
            if result.transport_error or result.exit_code not in (None,0): raise FirmwareError('explicit firmware rollback failed')
            self._event(run_id,'FIRMWARE_ROLLBACK_COMPLETED',{'target':result.target})
            return adapter.wait_ready()
        except Exception as exc:
            self._event(run_id,'FIRMWARE_ROLLBACK_FAILED',{'error':str(exc)}); raise

    def _event(self, run_id, event_type, details):
        if not run_id or self.event_repository is None: return
        if self.run_repository is not None and self.run_repository.get(run_id) is None: raise FirmwareError(f'Run not found for firmware audit: {run_id}')
        self.event_repository.append(LifecycleEvent(event_id=self.id_generator(),run_id=run_id,event_type=event_type,occurred_at=datetime.now(timezone.utc),details=details))