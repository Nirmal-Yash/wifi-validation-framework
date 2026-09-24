from pathlib import Path
import hashlib
import pytest

from lib.adapters import DeviceProfile, FakeDeviceAdapter, FakeFirmwareAdapter, FirmwareAuthorization, FirmwareImage, FirmwareValidationError, FirmwareAuthorizationError, VirtualLinuxDeviceAdapter, OpenWrtDeviceAdapter
from lib.services.command_runner import CommandResult
from lib.services.firmware_service import FirmwareOperationService

def auth(operation):
    return FirmwareAuthorization("test-operator","adapter contract test",True,operation)

def make_image(tmp_path, model="simulator", content=b"firmware"):
    path=tmp_path/"firmware.bin"; path.write_bytes(content)
    return FirmwareImage.from_path(path,version="v2.0",compatible_models=(model,),expected_sha256=hashlib.sha256(content).hexdigest())

def test_nominal_lifecycle(tmp_path):
    device=FakeDeviceAdapter(); result=FirmwareOperationService().update(adapter=FakeFirmwareAdapter(device),image=make_image(tmp_path),authorization=auth("FLASH"))
    assert result.stage=="VERSION_VERIFIED" and result.verified_version=="v2.0"

def test_authorization_is_required(tmp_path):
    bad=FirmwareAuthorization("","","false"=="true","FLASH")
    with pytest.raises(FirmwareAuthorizationError): FirmwareOperationService().update(adapter=FakeFirmwareAdapter(FakeDeviceAdapter()),image=make_image(tmp_path),authorization=bad)

def test_model_mismatch_blocks_before_upload(tmp_path):
    adapter=FakeFirmwareAdapter(FakeDeviceAdapter())
    with pytest.raises(FirmwareValidationError): FirmwareOperationService().update(adapter=adapter,image=make_image(tmp_path,model="other"),authorization=auth("FLASH"))
    assert adapter.uploaded is None

def test_hash_mismatch_is_rejected(tmp_path):
    path=tmp_path/"firmware.bin"; path.write_bytes(b"firmware")
    image=FirmwareImage.from_path(path,version="v2.0",compatible_models=("simulator",),expected_sha256="0"*64)
    validation=FakeFirmwareAdapter(FakeDeviceAdapter()).validate_image(image)
    assert not validation.valid and validation.reasons

def test_flash_failure_is_not_retried_or_rolled_back(tmp_path):
    device=FakeDeviceAdapter(scenario="flash_failure"); adapter=FakeFirmwareAdapter(device)
    with pytest.raises(Exception,match="flash failed"): FirmwareOperationService().update(adapter=adapter,image=make_image(tmp_path),authorization=auth("FLASH"))
    assert device.firmware_version=="v1.0"

def test_reboot_failure_does_not_trigger_rollback(tmp_path):
    device=FakeDeviceAdapter(scenario="reboot_failure"); adapter=FakeFirmwareAdapter(device)
    with pytest.raises(Exception,match="reboot failed"): FirmwareOperationService().update(adapter=adapter,image=make_image(tmp_path),authorization=auth("FLASH"))
    assert device.firmware_version=="v2.0"

def test_rollback_is_explicit(tmp_path):
    device=FakeDeviceAdapter(); adapter=FakeFirmwareAdapter(device); service=FirmwareOperationService()
    service.update(adapter=adapter,image=make_image(tmp_path),authorization=auth("FLASH"))
    adapter.rollback(authorization=auth("ROLLBACK"))
    assert device.firmware_version=="v1.0"

def test_capabilities_are_machine_readable():
    caps=FakeDeviceAdapter().capabilities().as_dict()
    assert caps["supports_firmware_flash"] and caps["supports_rollback"]


class StubRunner:
    def __init__(self, output):
        self.output=output
    def execute(self, target, command, **kwargs):
        return CommandResult(command_id="stub",target=target,command_category="device",safe_display_command=command,stdout=self.output,exit_code=0,transport="fake")
    def execute_shell(self, target, command, **kwargs):
        return self.execute(target, command, **kwargs)


def test_openwrt_profile_declares_firmware_capabilities():
    profile=DeviceProfile.openwrt_defaults(device_id="router",host="127.0.0.1",username="root")
    assert profile.device_type=="openwrt"
    assert profile.capabilities.supports_firmware_flash is True
    assert profile.firmware_flash_command.startswith("sysupgrade")


def test_virtual_linux_version_uses_profile_command():
    profile=DeviceProfile(device_id="vm",host="127.0.0.1",username="admin",version_command="cat /etc/version")
    adapter=VirtualLinuxDeviceAdapter.from_profile(profile,StubRunner("v1.2.3"))
    assert adapter.version().firmware_version=="v1.2.3"


def test_openwrt_version_parser_accepts_ubus_payload():
    profile=DeviceProfile.openwrt_defaults(device_id="router",host="127.0.0.1",username="root")
    adapter=OpenWrtDeviceAdapter.from_profile(profile,StubRunner('{"release":{"version":"23.05.5"}}'))
    assert adapter.version().firmware_version=="23.05.5"
