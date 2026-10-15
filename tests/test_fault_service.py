import pytest

from lib.services import FaultDefinition, FaultService
from lib.services.command_runner import CommandResult


class FakeRunner:
    def __init__(self):
        self.commands = []
        self.fail_on = set()

    def execute_shell(self, target, command, **kwargs):
        self.commands.append((target, command, kwargs["command_category"]))
        if len(self.commands) in self.fail_on:
            raise RuntimeError(f"forced failure {len(self.commands)}")
        return CommandResult(
            command_id=f"cmd-{len(self.commands)}",
            target=target,
            command_category=kwargs["command_category"],
            safe_display_command=command,
            stdout="ok" if "echo ok" in command else "",
            exit_code=None,
            transport="fake",
        )


def make_fault() -> FaultDefinition:
    return FaultDefinition(
        fault_id="test.fault",
        target="client_vm",
        apply_commands=("sudo ip link set wlan0 down",),
        restore_commands=("sudo ip link set wlan0 up",),
        description="test fault",
    )


def test_fault_service_restores_after_context():
    runner = FakeRunner()
    service = FaultService(runner)

    with service.context(make_fault()):
        assert runner.commands[0][1].endswith("wlan0 down")

    assert runner.commands[1][1].endswith("wlan0 up")
    assert runner.commands[0][2] == "fault.apply.test.fault"
    assert runner.commands[1][2] == "fault.restore.test.fault"


def test_fault_service_restores_when_validation_raises():
    runner = FakeRunner()
    service = FaultService(runner)

    with pytest.raises(RuntimeError, match="validation failed"):
        with service.context(make_fault()):
            raise RuntimeError("validation failed")

    assert runner.commands[-1][1].endswith("wlan0 up")


def test_fault_service_restores_after_partial_apply_failure():
    runner = FakeRunner()
    runner.fail_on.add(2)
    service = FaultService(runner)
    fault = FaultDefinition(
        fault_id="test.partial",
        target="client_vm",
        apply_commands=(
            "sudo ip link set wlan0 down",
            "sudo wpa_cli -i wlan0 disconnect",
        ),
        restore_commands=("sudo ip link set wlan0 up",),
        description="partial apply",
    )

    with pytest.raises(RuntimeError, match="forced failure"):
        with service.context(fault):
            pass

    assert runner.commands[-1][1].endswith("wlan0 up")


def test_fault_service_restore_runs_all_commands():
    runner = FakeRunner()
    service = FaultService(runner)
    fault = FaultDefinition(
        fault_id="test.multi",
        target="router1",
        apply_commands=("sudo systemctl stop dnsmasq",),
        restore_commands=(
            "sudo systemctl start dnsmasq",
            "sudo pgrep dnsmasq",
        ),
        description="test multi-command restore",
    )

    service.apply(fault)
    service.restore(fault)

    assert [item[1] for item in runner.commands] == [
        "sudo systemctl stop dnsmasq",
        "sudo systemctl start dnsmasq",
        "sudo pgrep dnsmasq",
    ]


def test_fault_service_restore_verification_is_enforced():
    runner = FakeRunner()
    service = FaultService(runner)
    fault = FaultDefinition(
        fault_id="test.verify",
        target="client_vm",
        apply_commands=("sudo ip link set wlan0 down",),
        restore_commands=("sudo echo ok",),
        restore_checks=(("sudo echo ok", ("ok",)),),
        description="restore verification",
    )

    with service.context(fault):
        pass

    assert any(category == "fault.verify.test.verify" for _, _, category in runner.commands)


class WifiAssociationRunner(FakeRunner):
    def __init__(self, status_output: str, link_output: str):
        super().__init__()
        self.status_output = status_output
        self.link_output = link_output

    def execute_shell(self, target, command, **kwargs):
        self.commands.append((target, command, kwargs["command_category"]))
        if "wpa_cli" in command and "status" in command:
            output = self.status_output
        elif "iw dev" in command and " link" in command:
            output = self.link_output
        else:
            output = "1234" if "pgrep wpa_supplicant" in command else ""
        return CommandResult(
            command_id=f"cmd-{len(self.commands)}",
            target=target,
            command_category=kwargs["command_category"],
            safe_display_command=command,
            stdout=output,
            exit_code=0,
            transport="fake",
        )


def make_wifi_restore_fault():
    return FaultDefinition(
        fault_id="wifi.restore_test",
        target="client_vm",
        apply_commands=("sudo ip link set wlan0 down",),
        restore_commands=("sudo ip link set wlan0 up",),
        description="test WiFi association restoration",
        restore_association_interface="wlan0",
        restore_association_ssid="TestNet_5G",
    )


def test_wifi_restore_accepts_driver_association_when_wpa_state_is_omitted():
    runner = WifiAssociationRunner(
        status_output=(
            "ssid=TestNet_5G\nkey_mgmt=WPA2-PSK\n"
            "pairwise_cipher=CCMP\ngroup_cipher=CCMP\n"
        ),
        link_output=(
            "Connected to 02:00:00:00:00:00 (on wlan0)\n"
            "\tSSID: TestNet_5G\n"
        ),
    )

    FaultService(runner).restore(make_wifi_restore_fault())


def test_wifi_restore_rejects_explicit_disconnected_state(monkeypatch):
    runner = WifiAssociationRunner(
        status_output=(
            "ssid=TestNet_5G\nwpa_state=DISCONNECTED\n"
            "key_mgmt=WPA2-PSK\npairwise_cipher=CCMP\ngroup_cipher=CCMP\n"
        ),
        link_output=(
            "Connected to 02:00:00:00:00:00 (on wlan0)\n"
            "\tSSID: TestNet_5G\n"
        ),
    )
    monkeypatch.setattr("lib.services.fault_service.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="association verification failed"):
        FaultService(runner).restore(make_wifi_restore_fault())


def test_wifi_restore_rejects_different_driver_ssid(monkeypatch):
    runner = WifiAssociationRunner(
        status_output=(
            "ssid=TestNet_5G\nkey_mgmt=WPA2-PSK\n"
            "pairwise_cipher=CCMP\ngroup_cipher=CCMP\n"
        ),
        link_output=(
            "Connected to 02:00:00:00:00:01 (on wlan0)\n"
            "\tSSID: OtherNet\n"
        ),
    )
    monkeypatch.setattr("lib.services.fault_service.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="association verification failed"):
        FaultService(runner).restore(make_wifi_restore_fault())


def test_wifi_restore_rejects_missing_driver_link(monkeypatch):
    runner = WifiAssociationRunner(
        status_output=(
            "ssid=TestNet_5G\nwpa_state=COMPLETED\n"
            "key_mgmt=WPA2-PSK\npairwise_cipher=CCMP\ngroup_cipher=CCMP\n"
        ),
        link_output="Not connected.\n",
    )
    monkeypatch.setattr("lib.services.fault_service.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="association verification failed"):
        FaultService(runner).restore(make_wifi_restore_fault())


def test_wifi_restore_requires_wpa2_security_fields(monkeypatch):
    runner = WifiAssociationRunner(
        status_output="ssid=TestNet_5G\n",
        link_output=(
            "Connected to 02:00:00:00:00:00 (on wlan0)\n"
            "\tSSID: TestNet_5G\n"
        ),
    )
    monkeypatch.setattr("lib.services.fault_service.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="association verification failed"):
        FaultService(runner).restore(make_wifi_restore_fault())
