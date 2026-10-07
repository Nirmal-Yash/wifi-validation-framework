from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib

@dataclass
class FakeDeviceAdapter:
    device_id: str = 'fw_simulator'
    model: str = 'simulator'
    firmware_version: str = 'v1.0'
    scenario: str = 'nominal'
    def __post_init__(self):
        from .device import DeviceCapabilities, DeviceProfile
        self.profile = DeviceProfile(device_id=self.device_id, host='simulator', username='simulator', device_type='simulator', model=self.model,
            capabilities=DeviceCapabilities(supports_firmware_flash=True, supports_rollback=True, supports_ssh=False),
            version_command='true', health_command='true')
    def identify(self):
        return self.version()

    def connect(self):
        if self.scenario == 'unavailable': raise RuntimeError('simulated device unavailable')
    def disconnect(self): return None
    def health(self):
        from .device import DeviceHealth
        return DeviceHealth(self.device_id, self.scenario != 'unavailable', 'simulated health', {'scenario': self.scenario})
    def diagnostics(self): return {'scenario': self.scenario, 'firmware_version': self.firmware_version}
    def capabilities(self): return self.profile.capabilities
    def version(self):
        from .device import DeviceIdentity
        return DeviceIdentity(self.device_id, self.model, 'simulator', self.firmware_version, 'simulator', self.capabilities())
    def _result(self, code=0, output='OK'):
        from lib.services.command_runner import CommandResult
        return CommandResult(command_id='fake', target=self.device_id, command_category='fake_firmware', safe_display_command='fake', stdout=output, exit_code=code, transport='fake')
    def execute(self, command): return self._result(output=command)
    def execute_shell(self, command): return self._result(output=command)
    def wifi_state(self): return self._result(output='SSID=SIMULATOR')
    def network_state(self): return self._result(output='wlan0 UP')
    def reboot(self, *, authorization):
        authorization.require('REBOOT')
        return self._result(1, 'reboot failed') if self.scenario == 'reboot_failure' else self._result()
    def upload(self, local_path, remote_path): return hashlib.sha256(Path(local_path).read_bytes()).hexdigest()

class FakeFirmwareAdapter:
    def __init__(self, device): self.device, self.uploaded, self.prepared = device, None, False
    def identify(self): return self.device.version()
    def validate_image(self, image):
        from .firmware import FirmwareValidationResult
        digest=hashlib.sha256(Path(image.path).read_bytes()).hexdigest()
        reasons=[]
        if image.expected_sha256 and digest != image.expected_sha256.lower(): reasons.append('SHA-256 does not match expected image hash')
        compatible=not image.compatible_models or self.device.model in image.compatible_models
        if not compatible: reasons.append('image model mismatch')
        return FirmwareValidationResult(not reasons, image.version, digest, None, self.device.device_id, self.device.model, compatible, tuple(reasons))
    def upload(self, image, *, authorization):
        authorization.require('UPLOAD'); validation=self.validate_image(image)
        from .firmware import FirmwareValidationError
        if not validation.valid: raise FirmwareValidationError('; '.join(validation.reasons))
        self.uploaded='/tmp/'+Path(image.path).name; return self.uploaded
    def prepare(self, remote_path, image, *, authorization):
        authorization.require('PREPARE')
        if self.uploaded != remote_path: return self.device._result(1, 'missing upload')
        self.prepared=True; return self.device._result()
    def flash(self, remote_path, image, *, authorization):
        authorization.require('FLASH')
        if self.device.scenario == 'flash_failure': return self.device._result(1, 'flash failed')
        self.device.firmware_version=image.version; return self.device._result()
    def reboot(self, *, authorization): return self.device.reboot(authorization=authorization)
    def wait_ready(self, timeout_sec=120, interval_sec=2):
        if self.device.scenario == 'reboot_failure': raise RuntimeError('simulated reboot failure')
        return self.device.version()
    def verify_version(self, expected_version):
        if self.device.firmware_version != expected_version: raise RuntimeError('version mismatch')
        return self.device.version()
    def rollback(self, *, authorization):
        authorization.require('ROLLBACK')
        if self.device.scenario == 'rollback_failure': return self.device._result(1, 'rollback failed')
        self.device.firmware_version='v1.0'; return self.device._result()