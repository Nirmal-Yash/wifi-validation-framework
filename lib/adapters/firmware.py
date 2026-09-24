from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import time
from typing import Any, Protocol, Sequence

from lib.services.command_security import CommandSecurityPolicy, SecureCommandRunner
from lib.services.command_runner import CommandResult, CommandRunner
from .device import DeviceAdapter, DeviceAdapterError, DeviceCapabilityError, DeviceIdentity

class FirmwareError(RuntimeError): pass
class FirmwareValidationError(FirmwareError): pass
class FirmwareAuthorizationError(PermissionError, FirmwareError): pass

@dataclass(frozen=True, slots=True)
class FirmwareAuthorization:
    actor: str
    reason: str
    authorized: bool
    operation: str
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    def require(self, operation: str) -> None:
        if operation != self.operation or not self.authorized or not self.actor.strip() or not self.reason.strip():
            raise FirmwareAuthorizationError(f'explicit {operation} authorization is required')

@dataclass(frozen=True, slots=True)
class FirmwareImage:
    path: Path
    version: str
    compatible_models: frozenset[str] = frozenset()
    expected_sha256: str | None = None
    signature_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    @classmethod
    def from_path(cls, path: str | Path, *, version: str, compatible_models: Sequence[str] = (), expected_sha256: str | None = None, signature_path: str | Path | None = None, metadata: dict[str, Any] | None = None) -> 'FirmwareImage':
        return cls(Path(path), version, frozenset(compatible_models), expected_sha256.lower() if expected_sha256 else None, Path(signature_path) if signature_path else None, metadata or {})

@dataclass(frozen=True, slots=True)
class FirmwareValidationResult:
    valid: bool
    image_version: str
    sha256: str
    signature_verified: bool | None
    device_id: str
    device_model: str
    compatible: bool
    reasons: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class FirmwareOperationResult:
    operation: str
    device_id: str
    image_version: str
    stage: str
    verified_version: str | None
    uploaded_remote_path: str | None
    validation: FirmwareValidationResult
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class SignatureVerifier(Protocol):
    def verify(self, image: Path, signature: Path) -> bool: ...

class GPGSignatureVerifier:
    def __init__(self, executable: str = 'gpg'): self.executable = executable
    def verify(self, image: Path, signature: Path) -> bool:
        result = subprocess.run([self.executable, '--batch', '--verify', str(signature), str(image)], capture_output=True, text=True, check=False, timeout=20)
        return result.returncode == 0

class FirmwareAdapter(Protocol):
    def identify(self) -> DeviceIdentity: ...
    def validate_image(self, image: FirmwareImage) -> FirmwareValidationResult: ...
    def upload(self, image: FirmwareImage, *, authorization: FirmwareAuthorization) -> str: ...
    def prepare(self, remote_path: str, image: FirmwareImage, *, authorization: FirmwareAuthorization) -> CommandResult: ...
    def flash(self, remote_path: str, image: FirmwareImage, *, authorization: FirmwareAuthorization) -> CommandResult: ...
    def reboot(self, *, authorization: FirmwareAuthorization) -> CommandResult: ...
    def wait_ready(self, timeout_sec: int = 120, interval_sec: int = 2) -> DeviceIdentity: ...
    def verify_version(self, expected_version: str) -> DeviceIdentity: ...
    def rollback(self, *, authorization: FirmwareAuthorization) -> CommandResult: ...

class SSHFirmwareAdapter:
    def __init__(self, device: DeviceAdapter, *, firmware_command_runner: CommandRunner | None = None, signature_verifier: SignatureVerifier | None = None):
        self.device = device
        self.signature_verifier = signature_verifier
        if firmware_command_runner is None:
            raw = getattr(device.command_runner, 'transport', None) or device.command_runner
            target = device.profile.device_id
            policy = CommandSecurityPolicy(
                allowed_executables_by_target={target: frozenset({'cat','echo','sha256sum','stat','test','sysupgrade','reboot','ubus'})},
                destructive_prefixes_by_target={target: (('sysupgrade',), ('reboot',))},
                allow_destructive=True,
            )
            firmware_command_runner = SecureCommandRunner(raw, security_policy=policy)
        self.firmware_command_runner = firmware_command_runner

    def identify(self) -> DeviceIdentity: return self.device.version()

    def validate_image(self, image: FirmwareImage) -> FirmwareValidationResult:
        if not image.path.is_file(): raise FirmwareValidationError(f'firmware image does not exist: {image.path}')
        digest = hashlib.sha256()
        with image.path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''): digest.update(chunk)
        sha256 = digest.hexdigest()
        reasons = []
        if image.expected_sha256 and sha256.lower() != image.expected_sha256.lower(): reasons.append('SHA-256 does not match expected image hash')
        identity = self.identify()
        compatible = not image.compatible_models or identity.model in image.compatible_models
        if not compatible: reasons.append(f'image is incompatible with device model {identity.model}')
        signature_verified = None
        if image.signature_path is not None:
            if self.signature_verifier is None: raise FirmwareValidationError('firmware signature supplied but no verifier configured')
            signature_verified = self.signature_verifier.verify(image.path, image.signature_path)
            if not signature_verified: reasons.append('detached firmware signature verification failed')
        valid = bool(image.version.strip()) and not reasons
        return FirmwareValidationResult(valid, image.version, sha256, signature_verified, identity.device_id, identity.model, compatible, tuple(reasons))

    def upload(self, image: FirmwareImage, *, authorization: FirmwareAuthorization) -> str:
        authorization.require('UPLOAD')
        validation = self.validate_image(image)
        if not validation.valid: raise FirmwareValidationError('; '.join(validation.reasons) or 'firmware image is invalid')
        remote = self._remote_path(image)
        uploaded_hash = self.device.upload(image.path, remote)
        if uploaded_hash.lower() != validation.sha256.lower(): raise FirmwareError('local/upload firmware digest mismatch')
        return remote

    def prepare(self, remote_path: str, image: FirmwareImage, *, authorization: FirmwareAuthorization) -> CommandResult:
        authorization.require('PREPARE')
        result = self.firmware_command_runner.execute(self.device.profile.device_id, f'sha256sum {self._remote_arg(remote_path)}', command_category='firmware_prepare', idempotent=True)
        if result.transport_error or result.exit_code not in (None, 0): raise FirmwareError('remote firmware integrity check failed to execute')
        remote_hash = result.stdout.strip().split()[0] if result.stdout.strip() else ''
        validation = self.validate_image(image)
        if remote_hash.lower() != validation.sha256.lower(): raise FirmwareError('remote firmware hash does not match validated image')
        return result

    def flash(self, remote_path: str, image: FirmwareImage, *, authorization: FirmwareAuthorization) -> CommandResult:
        authorization.require('FLASH')
        if not self.device.profile.capabilities.supports_firmware_flash: raise DeviceCapabilityError(f'device {self.device.profile.device_id} does not support firmware flash')
        validation = self.validate_image(image)
        if not validation.valid: raise FirmwareValidationError('; '.join(validation.reasons) or 'firmware image is invalid')
        command = self.device.profile.firmware_flash_command.format(remote_path=self._remote_arg(remote_path))
        return self.firmware_command_runner.execute(self.device.profile.device_id, command, command_category='firmware_flash', idempotent=False)

    def reboot(self, *, authorization: FirmwareAuthorization) -> CommandResult:
        authorization.require('REBOOT')
        return self.firmware_command_runner.execute(self.device.profile.device_id, self.device.profile.reboot_command, command_category='firmware_reboot', idempotent=False)

    def wait_ready(self, timeout_sec: int = 120, interval_sec: int = 2) -> DeviceIdentity:
        deadline = time.monotonic() + timeout_sec
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                if self.device.health().healthy: return self.device.version()
            except Exception as exc: last_error = exc
            time.sleep(interval_sec)
        raise DeviceAdapterError(f'device did not become ready within {timeout_sec}s: {last_error}')

    def verify_version(self, expected_version: str) -> DeviceIdentity:
        identity = self.identify()
        if identity.firmware_version != expected_version: raise FirmwareError(f'firmware version verification failed: expected {expected_version}, observed {identity.firmware_version}')
        return identity

    def rollback(self, *, authorization: FirmwareAuthorization) -> CommandResult:
        authorization.require('ROLLBACK')
        if not self.device.profile.capabilities.supports_rollback: raise DeviceCapabilityError(f'device {self.device.profile.device_id} does not support rollback')
        command = self.device.profile.firmware_rollback_command
        if not command: raise FirmwareError('rollback is declared but no rollback command is configured')
        return self.firmware_command_runner.execute(self.device.profile.device_id, command, command_category='firmware_rollback', idempotent=False)

    def _remote_path(self, image: FirmwareImage) -> str:
        digest = hashlib.sha256(image.path.read_bytes()).hexdigest()[:16]
        directory = self.device.profile.remote_firmware_directory.rstrip('/')
        return f'{directory}/{digest}-{image.version}.bin'

    @staticmethod
    def _remote_arg(remote_path: str) -> str:
        import shlex
        if not remote_path.startswith('/') or '..' in remote_path.split('/'): raise ValueError('invalid remote firmware path')
        return shlex.quote(remote_path)