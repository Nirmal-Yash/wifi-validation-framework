from __future__ import annotations

import subprocess

import pytest

from lib.services.linux_wifi_guest_provisioning import (
    LinuxWiFiGuestProvisioningConflict,
    LinuxWiFiGuestProvisioningService,
)


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        return subprocess.CompletedProcess(command, 0, "", "")


class FakeHostNetwork:
    def __init__(self, can_apply=True):
        self.can_apply = can_apply
        self.calls = []

    def plan(self):
        self.calls.append("plan")
        return {"can_apply": self.can_apply, "mutations": {}}

    def apply(self, *, confirmed, actor):
        self.calls.append(("apply", confirmed, actor))
        return {"status": "APPLIED"}


class FakeLock:
    def __init__(self):
        self.acquired = []
        self.released = 0

    def acquire(self, resource, owner, *, timeout, lease_seconds):
        self.acquired.append((resource, owner, timeout, lease_seconds))
        return self

    def release(self):
        self.released += 1


def make_service(tmp_path, runner=None, *, host=None, lock=None):
    return LinuxWiFiGuestProvisioningService(
        host or FakeHostNetwork(),
        runner=runner or FakeRunner(),
        system="Linux",
        effective_uid=1000,
        module_path=tmp_path / "mac80211_hwsim",
        resource_lock_manager=lock or FakeLock(),
        sleep=lambda _seconds: None,
        ssh_probe=lambda _host, _username, _password: None,
    )


def test_guest_command_runner_uses_argument_vectors_shell_false_and_sudo_n():
    runner = FakeRunner()
    service = LinuxWiFiGuestProvisioningService(
        FakeHostNetwork(), runner=runner, system="Linux", effective_uid=1000,
    )
    service._run(["ip", "addr", "replace", "10.10.10.1/24", "dev", "virbr0"], privileged=True)
    command, kwargs = runner.calls[0]
    assert command[:2] == ["sudo", "-n"]
    assert kwargs["shell"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == service.COMMAND_TIMEOUT

    with pytest.raises(TypeError, match="argument sequences"):
        service._run("ip addr show")  # type: ignore[arg-type]


def test_guest_configuration_secrets_are_delivered_over_stdin_not_argv(tmp_path):
    runner = FakeRunner()
    service = make_service(tmp_path, runner)
    service._write_guest_file(
        "GNS3.wifi-client.1", "/etc/wpa_supplicant.conf",
        'network={\n ssid="TestNet_5G"\n psk="secret-passphrase"\n}\n',
    )
    command, kwargs = runner.calls[0]
    assert command[:5] == [
        "docker", "exec", "-i", "GNS3.wifi-client.1", "sh",
    ]
    assert kwargs["shell"] is False
    assert "secret-passphrase" not in command
    assert "secret-passphrase" in kwargs["input"]


def test_admin_password_is_sent_to_chpasswd_using_stdin():
    calls = []

    def runner(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        stdout = "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*" if "ss" in command else ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    service = LinuxWiFiGuestProvisioningService(
        FakeHostNetwork(), runner=runner, system="Linux", effective_uid=1000,
        sleep=lambda _seconds: None,
    )
    service._set_admin("GNS3.hostapd-ap.1", "alpine", "highly-private-password")
    command, kwargs = next(item for item in calls if item[0][-1] == "chpasswd")
    assert command == ["docker", "exec", "-i", "GNS3.hostapd-ap.1", "chpasswd"]
    assert "highly-private-password" not in command
    assert kwargs["input"] == "admin:highly-private-password" + chr(10)
    assert kwargs["shell"] is False


def test_container_resolution_rejects_missing_and_ambiguous_gns3_nodes(tmp_path):
    service = make_service(tmp_path)
    def response(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0,
            "GNS3.frr-router.1" + chr(10) + "GNS3.frr-router.2" + chr(10),
            "",
        )
    service.runner = response
    with pytest.raises(LinuxWiFiGuestProvisioningConflict, match="ambiguous"):
        service._find_containers()


def test_wifi_credentials_and_ssid_are_validated_before_mutations(tmp_path):
    service = make_service(tmp_path)
    passwords = {
        "router1": "router-secret",
        "ap": "ap-secret",
        "client": "client-secret",
        "monitor": "monitor-secret",
        "wifi_psk": "valid-wpa-passphrase",
    }
    assert service._validate_passwords(passwords) == passwords
    with pytest.raises(ValueError, match="SSID"):
        service._validate_wifi("valid-ssid\ninterface=eth0", "valid-wpa-passphrase")
    with pytest.raises(ValueError, match="WPA2"):
        service._validate_wifi("TestNet_5G", "short")
    with pytest.raises(ValueError, match="provide"):
        service._validate_passwords({"router1": "only-one"})


def test_wpa_configuration_escapes_quoted_values_and_keeps_secret_off_arguments(tmp_path):
    service = make_service(tmp_path)
    content = service._wpa_config('Test"Net', 'pass"word\\value')
    assert 'ssid="Test\\"Net"' in content
    assert "pass" + chr(92) + '"word' in content
    assert "pass\"word" in content


def test_hwsim_reuses_existing_guest_radios_without_module_reload(tmp_path):
    runner = FakeRunner()
    service = make_service(tmp_path, runner)
    service._interface_state = lambda _container, interface: {"exists": True, "carrier": True}
    result = service._ensure_hwsim("GNS3.hostapd-ap.1", "GNS3.wifi-client.1")
    assert result == {"ap_phy": "EXISTING", "client_phy": "EXISTING", "reused": True}
    assert not any("modprobe" in command for command, _kwargs in runner.calls)


def test_hwsim_shortage_fails_closed_and_never_unloads_module(tmp_path):
    runner = FakeRunner()
    module_path = tmp_path / "mac80211_hwsim"
    module_path.mkdir()
    service = make_service(tmp_path, runner)
    service.module_path = module_path
    service._interface_state = lambda container, interface: {
        "exists": container == "GNS3.hostapd-ap.1",
        "carrier": True,
    }
    service._host_phys = lambda: []
    with pytest.raises(LinuxWiFiGuestProvisioningConflict, match="refusing to unload"):
        service._ensure_hwsim("GNS3.hostapd-ap.1", "GNS3.wifi-client.1")
    assert not any("modprobe" in command for command, _kwargs in runner.calls)


def test_hwsim_loads_missing_module_once_and_assigns_distinct_guest_radio(tmp_path):
    runner = FakeRunner()
    service = make_service(tmp_path, runner)
    service._interface_state = lambda container, interface: {
        "exists": container == "GNS3.hostapd-ap.1",
        "carrier": True,
    }
    service._host_phys = lambda: ["phy0"]
    moved = []
    service._place_radio = lambda phy, container, label: moved.append((phy, container, label))
    result = service._ensure_hwsim("GNS3.hostapd-ap.1", "GNS3.wifi-client.1")
    assert result == {"ap_phy": "EXISTING", "client_phy": "phy0", "reused": False}
    commands = [command for command, _kwargs in runner.calls]
    assert ["sudo", "-n", "modprobe", "mac80211_hwsim", "radios=2"] in commands
    assert moved == [("phy0", "GNS3.wifi-client.1", "Client")]
    assert not any("modprobe" in command and "-r" in command for command in commands)


def test_docker_access_falls_back_to_noninteractive_sudo_without_shell():
    calls = []

    def runner(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        code = 0 if command[:3] == ["sudo", "-n", "docker"] else 1
        return subprocess.CompletedProcess(command, code, "", "")

    service = LinuxWiFiGuestProvisioningService(
        FakeHostNetwork(), runner=runner, system="Linux", effective_uid=1000,
    )
    service._ensure_docker_access()
    assert service.docker_prefix == ("sudo", "-n", "docker")
    assert calls[0][0] == ["docker", "info"]
    assert calls[1][0] == ["sudo", "-n", "docker", "info"]
    assert all(call[1]["shell"] is False for call in calls)


def test_plan_is_read_only_and_reports_guest_and_host_preflight(tmp_path):
    runner = FakeRunner()
    host = FakeHostNetwork()
    service = make_service(tmp_path, runner, host=host)
    service._find_containers = lambda: {
        "frr-router": "GNS3.frr-router.1",
        "hostapd-ap": "GNS3.hostapd-ap.1",
        "wifi-client": "GNS3.wifi-client.1",
        "monitor": "GNS3.monitor.1",
    }
    service._inspect_container = lambda name: {"name": name, "running": True, "pid": 100}
    service._interface_state = lambda container, interface: {"exists": True, "carrier": True}
    report = service.plan()
    assert report["status"] == "PLANNED"
    assert report["can_apply"] is True
    assert report["safety"]["requires_explicit_confirmation"] is True
    assert report["safety"]["unloads_hwsim"] is False
    assert host.calls == ["plan"]
    assert [call[0] for call in runner.calls] == [["docker", "info"]]


def test_apply_requires_confirmation_before_preflight_or_lock(tmp_path):
    host = FakeHostNetwork()
    lock = FakeLock()
    service = make_service(tmp_path, host=host, lock=lock)
    with pytest.raises(LinuxWiFiGuestProvisioningConflict, match="confirmation"):
        service.apply(
            lab_id="LAB-1",
            actor="operator",
            passwords={},
            confirmed=False,
        )
    assert host.calls == []
    assert lock.acquired == []


def test_apply_rejects_preflight_conflict_before_host_or_guest_mutations(tmp_path):
    host = FakeHostNetwork(can_apply=False)
    lock = FakeLock()
    service = make_service(tmp_path, host=host, lock=lock)
    service.plan = lambda: {"can_apply": False, "conflicts": [{"code": "HOST_NETWORK_CONFLICT"}]}
    passwords = {
        "router1": "router-secret",
        "ap": "ap-secret",
        "client": "client-secret",
        "monitor": "monitor-secret",
        "wifi_psk": "valid-wpa-passphrase",
    }
    with pytest.raises(LinuxWiFiGuestProvisioningConflict, match="preflight"):
        service.apply(
            lab_id="LAB-1", actor="operator", passwords=passwords,
            confirmed=True,
        )
    assert host.calls == []
    assert lock.acquired == []
