from pathlib import Path
import hashlib
import pytest

from lib.adapters import DeviceProfile, DeviceCapabilityError, FakeDeviceAdapter, FakeFirmwareAdapter, FirmwareAuthorization, FirmwareImage, FirmwareValidationError, FirmwareAuthorizationError, SSHFirmwareAdapter, VirtualLinuxDeviceAdapter, OpenWrtDeviceAdapter
from lib.services.command_runner import CommandResult
from lib.services.firmware_service import FirmwareOperationService
from lib.services.resource_lock import ResourceLockError, ResourceLockManager

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

def test_firmware_mutation_respects_exclusive_device_lock(tmp_path):
    manager = ResourceLockManager(tmp_path / "locks")
    device = FakeDeviceAdapter()
    held = manager.acquire("device:" + device.identify().device_id, "runner:999", timeout=0)
    try:
        service = FirmwareOperationService(resource_lock_manager=manager)
        with pytest.raises(ResourceLockError):
            service.update(
                adapter=FakeFirmwareAdapter(device),
                image=make_image(tmp_path),
                authorization=auth("FLASH"),
            )
        assert device.firmware_version == "v1.0"
    finally:
        held.release()



def test_device_profile_parses_capability_strings_without_truthiness_bug():
    profile = DeviceProfile.from_mapping(
        "router",
        {
            "host": "127.0.0.1",
            "username": "root",
            "capabilities": {
                "supports_firmware_flash": "false",
                "supports_rollback": "0",
                "supports_reboot": "yes",
            },
        },
    )
    assert profile.capabilities.supports_firmware_flash is False
    assert profile.capabilities.supports_rollback is False
    assert profile.capabilities.supports_reboot is True


def test_device_profile_rejects_unknown_capability_boolean():
    with pytest.raises(ValueError, match="must be a boolean"):
        DeviceProfile.from_mapping(
            "router",
            {
                "host": "127.0.0.1",
                "username": "root",
                "capabilities": {"supports_rollback": "sometimes"},
            },
        )


def test_openwrt_mapping_defaults_to_firmware_capable_profile():
    profile = DeviceProfile.from_mapping(
        "router",
        {"host": "127.0.0.1", "username": "root", "device_type": "openwrt"},
    )
    assert profile.capabilities.supports_firmware_flash is True
    assert profile.capabilities.supports_wpa3 is True
    assert profile.capabilities.supports_rollback is False
    assert profile.version_parser == "openwrt-ubus"


def test_device_profile_resolves_environment_credentials(monkeypatch):
    monkeypatch.setenv("WIFI_TEST_ROUTER_PASSWORD", "resolved-secret")
    profile = DeviceProfile.from_mapping(
        "router",
        {
            "host": "127.0.0.1",
            "username": "root",
            "password": "__ENV__:WIFI_TEST_ROUTER_PASSWORD",
        },
    )
    assert profile.password == "resolved-secret"


def test_device_profile_fails_closed_when_environment_credential_missing(monkeypatch):
    monkeypatch.delenv("WIFI_MISSING_ROUTER_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="environment variable is unset"):
        DeviceProfile.from_mapping(
            "router",
            {
                "host": "127.0.0.1",
                "username": "root",
                "password": "__ENV__:WIFI_MISSING_ROUTER_PASSWORD",
            },
        )


def test_openwrt_version_regex_parser_matches_version_field():
    profile = DeviceProfile(
        device_id="router", host="127.0.0.1", username="root",
        device_type="openwrt", version_parser="regex",
    )
    adapter = OpenWrtDeviceAdapter.from_profile(profile, StubRunner("Version: 23.05.5"))
    assert adapter._parse_version("Version: 23.05.5") == "23.05.5"


def test_firmware_image_rejects_unsafe_version_and_hash(tmp_path):
    path = tmp_path / "firmware.bin"
    path.write_bytes(b"firmware")
    with pytest.raises(ValueError, match="safe version"):
        FirmwareImage.from_path(path, version="../v2.0")
    with pytest.raises(ValueError, match="64 hexadecimal"):
        FirmwareImage.from_path(path, version="v2.0", expected_sha256="not-a-hash")


def test_firmware_image_metadata_is_detached_and_immutable(tmp_path):
    path = tmp_path / "firmware.bin"
    path.write_bytes(b"firmware")
    metadata = {"release": {"channel": "stable"}, "tags": ["wifi", "router"]}
    image = FirmwareImage.from_path(path, version="v2.0", metadata=metadata)
    metadata["release"]["channel"] = "changed"
    metadata["tags"].append("mutable")
    assert image.metadata["release"]["channel"] == "stable"
    assert image.metadata["tags"] == ("wifi", "router")
    with pytest.raises(TypeError):
        image.metadata["release"]["channel"] = "mutable"


def test_firmware_remote_paths_are_confined_to_profile_directory():
    device = FakeDeviceAdapter()
    profile = DeviceProfile(
        device_id=device.device_id, host="127.0.0.1", username="root",
        device_type="openwrt", model=device.model,
        capabilities=device.capabilities(),
    )
    adapter = SSHFirmwareAdapter(device, firmware_command_runner=StubRunner("0" * 64))
    adapter.device.profile = profile
    assert "netregress" in adapter._remote_arg("/tmp/netregress/abc-v2.0.bin")
    with pytest.raises(ValueError, match="beneath the configured"):
        adapter._remote_arg("/tmp/other/firmware.bin")
    with pytest.raises(ValueError, match="beneath the configured"):
        adapter._remote_arg("/tmp/netregress/../outside.bin")


def test_firmware_reboot_respects_declared_capability():
    device = FakeDeviceAdapter()
    from lib.adapters import DeviceCapabilities
    device.profile = DeviceProfile(
        device_id=device.device_id, host="127.0.0.1", username="root",
        capabilities=DeviceCapabilities(supports_reboot=False),
    )
    adapter = SSHFirmwareAdapter(device, firmware_command_runner=StubRunner("ok"))
    with pytest.raises(DeviceCapabilityError, match="does not support reboot"):
        adapter.reboot(authorization=auth("REBOOT"))


def test_firmware_readiness_rejects_invalid_timeout():
    device = FakeDeviceAdapter()
    adapter = SSHFirmwareAdapter(device, firmware_command_runner=StubRunner("ok"))
    with pytest.raises(ValueError, match="positive finite"):
        adapter.wait_ready(timeout_sec=0)


def test_firmware_rollback_service_verifies_expected_version(tmp_path):
    device = FakeDeviceAdapter()
    adapter = FakeFirmwareAdapter(device)
    service = FirmwareOperationService(resource_lock_manager=ResourceLockManager(tmp_path / "locks"))
    result = service.rollback(
        adapter=adapter,
        authorization=auth("ROLLBACK"),
        expected_version="v1.0",
    )
    assert result.firmware_version == "v1.0"


def test_firmware_rollback_service_rejects_unexpected_version(tmp_path):
    device = FakeDeviceAdapter(firmware_version="v2.0")
    adapter = FakeFirmwareAdapter(device)
    service = FirmwareOperationService(resource_lock_manager=ResourceLockManager(tmp_path / "locks"))
    with pytest.raises(RuntimeError, match="version mismatch"):
        service.rollback(
            adapter=adapter,
            authorization=auth("ROLLBACK"),
            expected_version="v0.9",
        )
