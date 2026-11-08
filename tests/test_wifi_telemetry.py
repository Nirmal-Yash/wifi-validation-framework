from datetime import datetime, timezone
import json
from pathlib import Path
import pytest

from lib.domain.telemetry import (
    TelemetryEnvironmentClass,
    TelemetryMetric,
    TelemetryPoint,
)
from lib.services.wifi_telemetry import TelemetryCollectionError, WifiTelemetryService

SIGNAL_POLL = """\
RSSI=-47
LINKSPEED=433
NOISE=-95
FREQUENCY=5180
WIDTH=80
"""

IW_LINK = """\
Connected to 02:11:22:33:44:55 (on wlan0)
\tSSID: NetRegress
\tfreq: 5180
\tsignal: -48 dBm
\ttx bitrate: 433.3 MBit/s VHT-MCS 9 80MHz VHT-NSS 1
"""

STATION_DUMP = """\
Station 02:11:22:33:44:55 (on wlan0)
\tinactive time: 4 ms
\trx bitrate: 433.3 MBit/s VHT-MCS 9 80MHz VHT-NSS 1
\ttx bitrate: 433.3 MBit/s VHT-MCS 9 80MHz VHT-NSS 1
\ttx retries: 7
\ttx failed: 1
\tsignal: -48 dBm
"""

class FakeRunner:
    def __init__(self, outputs=None, *, exit_codes=None):
        self.outputs = outputs or {
            "wpa_cli": SIGNAL_POLL,
            "iw dev wlan0 link": IW_LINK,
            "iw dev wlan0 station dump": STATION_DUMP,
        }
        self.exit_codes = exit_codes or {}
        self.calls = []

    def execute(self, target, command, **kwargs):
        self.calls.append((target, command, kwargs))
        for prefix, output in self.outputs.items():
            if command.startswith(prefix):
                return type(
                    "Result",
                    (),
                    {
                        "transport_succeeded": True,
                        "transport_error": None,
                        "transport": "netmiko",
                        "exit_code": next(
                            (code for prefix, code in self.exit_codes.items()
                             if command.startswith(prefix)),
                            0,
                        ),
                        "stdout": output,
                    },
                )()
        return type(
            "Result",
            (),
            {
                "transport_succeeded": True,
                "transport_error": None,
                        "transport": "netmiko",
                "exit_code": 0,
                "stdout": "",
            },
        )()

def test_capture_parses_required_telemetry_and_environment_class():
    clock = lambda: datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)
    runner = FakeRunner()
    service = WifiTelemetryService(
        command_runner=runner,
        target="client_vm",
        environment_class=TelemetryEnvironmentClass.VIRTUAL_WIFI,
        clock=clock,
    )
    snapshot = service.capture(run_id="run-123", interface="wlan0")
    values = {point.metric: point.value for point in snapshot.points}
    assert values[TelemetryMetric.RSSI_DBM] == -47.0
    assert values[TelemetryMetric.SNR_DB] == 48.0
    assert values[TelemetryMetric.CHANNEL] == 36
    assert values[TelemetryMetric.FREQUENCY_MHZ] == 5180.0
    assert values[TelemetryMetric.BITRATE_MBPS] == 433.0
    assert values[TelemetryMetric.PHY_MODE] == "802.11ac (VHT)"
    assert values[TelemetryMetric.TX_RETRIES_TOTAL] == 7
    assert values[TelemetryMetric.TX_FAILED_TOTAL] == 1
    sources = {point.metric: point.source for point in snapshot.points}
    assert sources[TelemetryMetric.SNR_DB] == "wpa_cli.signal_poll"
    assert {point.environment_class for point in snapshot.points} == {TelemetryEnvironmentClass.VIRTUAL_WIFI}
    assert [call[1] for call in runner.calls] == [
        "wpa_cli -i wlan0 signal_poll",
        "iw dev wlan0 link",
        "iw dev wlan0 station dump",
    ]

def test_physical_environment_class_is_preserved_without_rf_claims():
    snapshot = WifiTelemetryService(
        command_runner=FakeRunner(),
        target="physical_ap",
        environment_class=TelemetryEnvironmentClass.PHYSICAL_WIFI,
    ).capture(run_id="run-physical")
    assert snapshot.environment_class == TelemetryEnvironmentClass.PHYSICAL_WIFI
    assert all(point.environment_class == TelemetryEnvironmentClass.PHYSICAL_WIFI for point in snapshot.points)

def test_missing_all_sources_is_not_promoted_to_fake_measurements():
    service = WifiTelemetryService(
        command_runner=FakeRunner(outputs={
            "wpa_cli": "",
            "iw dev wlan0 link": "",
            "iw dev wlan0 station dump": "",
        }),
        target="client_vm",
        environment_class=TelemetryEnvironmentClass.VIRTUAL_WIFI,
    )
    with pytest.raises(TelemetryCollectionError):
        service.capture(run_id="run-empty")

def test_invalid_interface_is_rejected_before_command_execution():
    runner = FakeRunner()
    service = WifiTelemetryService(
        command_runner=runner,
        target="client_vm",
        environment_class=TelemetryEnvironmentClass.VIRTUAL_WIFI,
    )
    with pytest.raises(ValueError):
        service.capture(run_id="run-123", interface="wlan0;rm")
    assert runner.calls == []

def test_json_serialization_repeats_environment_class_on_every_point(tmp_path):
    service = WifiTelemetryService(
        command_runner=FakeRunner(),
        target="client_vm",
        environment_class=TelemetryEnvironmentClass.VIRTUAL_WIFI,
    )
    snapshot = service.capture(run_id="run-json")
    path = service.write_json(snapshot, tmp_path / "telemetry.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["environment_class"] == "VIRTUAL_WIFI"
    assert payload["points"]
    assert all(point["environment_class"] == "VIRTUAL_WIFI" for point in payload["points"])


class FakeArtifactService:
    def __init__(self):
        self.calls = []

    def register_file(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


def test_capture_and_register_creates_immutable_paths(tmp_path):
    service = WifiTelemetryService(
        command_runner=FakeRunner(),
        target="client_vm",
        environment_class=TelemetryEnvironmentClass.VIRTUAL_WIFI,
        output_directory=tmp_path,
    )
    artifacts = FakeArtifactService()

    first = service.capture_and_register(
        run_id="run-repeat",
        artifact_service=artifacts,
        interface="wlan0",
    )
    second = service.capture_and_register(
        run_id="run-repeat",
        artifact_service=artifacts,
        interface="wlan0",
    )

    assert first[1]["path"] != second[1]["path"]
    assert Path(first[1]["path"]).is_file()
    assert Path(second[1]["path"]).is_file()



def test_nonzero_readonly_command_output_is_not_used_as_measurement():
    runner = FakeRunner(
        outputs={"wpa_cli": SIGNAL_POLL, "iw dev wlan0 link": "",
                 "iw dev wlan0 station dump": ""},
        exit_codes={"wpa_cli": 127},
    )
    service = WifiTelemetryService(
        command_runner=runner, target="client_vm",
        environment_class=TelemetryEnvironmentClass.VIRTUAL_WIFI,
    )
    with pytest.raises(TelemetryCollectionError):
        service.capture(run_id="run-command-failed")


def test_unknown_netmiko_exit_status_is_explicitly_retained_as_warning():
    runner = FakeRunner(exit_codes={
        "wpa_cli": None, "iw dev wlan0 link": None,
        "iw dev wlan0 station dump": None,
    })
    snapshot = WifiTelemetryService(
        command_runner=runner, target="client_vm",
        environment_class=TelemetryEnvironmentClass.VIRTUAL_WIFI,
    ).capture(run_id="run-netmiko")
    assert snapshot.points
    assert any("exit status is unavailable" in warning for warning in snapshot.warnings)


def test_telemetry_point_detaches_and_freezes_nested_metadata():
    metadata = {"target": "client_vm", "details": {"interfaces": ["wlan0"]}}
    point = TelemetryPoint(
        metric=TelemetryMetric.RSSI_DBM, value=-47.0, unit="dBm",
        environment_class=TelemetryEnvironmentClass.VIRTUAL_WIFI,
        source="iw.link", interface="wlan0",
        captured_at=datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc),
        metadata=metadata,
    )
    metadata["details"]["interfaces"].append("eth1")
    serialized = point.as_dict()
    assert serialized["metadata"]["details"]["interfaces"] == ["wlan0"]
    with pytest.raises(TypeError):
        point.metadata["target"] = "other"
    with pytest.raises(AttributeError):
        point.metadata["details"]["interfaces"].append("eth1")
