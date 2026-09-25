from pathlib import Path

from lib.domain import ArtifactType, EnvironmentHealthStatus, HealthObservationStatus
from lib.services import CommandResult, LabHealthService


class FakeRunner:
    def execute(self, target, command, **kwargs):
        command_text = command if isinstance(command, str) else " ".join(command)
        if target == "lab_host":
            if command_text.startswith("df "):
                output = "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda 10000000 1000 9000000 1% /"
                return CommandResult(\n            "cmd", target, "lab_health", command_text,\n            stdout=output,\n            exit_code=None if command_text.startswith("pgrep") else 0,\n            transport="fake",\n        )
            if command_text.startswith("timedatectl "):
                return CommandResult("cmd", target, "lab_health", command_text, stdout="yes\n", exit_code=0, transport="fake")
            return CommandResult("cmd", target, "lab_health", command_text, stdout="healthy\n", exit_code=0, transport="fake")

        if "nslookup" in command_text:
            output = "Server: 8.8.8.8\nAddress: 8.8.8.8\nName: google.com\nAddress: 142.250.0.1\n"
        elif command_text.startswith("ip -4 addr"):
            output = "2: wlan0: state UP\n    inet 192.168.122.30/24"
        elif command_text.startswith("pgrep"):
            output = "1234\n"
        elif command_text.startswith("iw phy"):
            output = "Wiphy phy0\nWiphy phy1\n"
        elif command_text.startswith("ip link"):
            output = "2: wlan0: <BROADCAST,UP,LOWER_UP>\n"
        else:
            output = "NETREGRESS_HEALTH_OK\n"
        return CommandResult("cmd", target, "lab_health", command_text, stdout=output, exit_code=0, transport="fake")


class FakeArtifactService:
    def __init__(self):
        self.calls = []

    def register_file(self, **kwargs):
        self.calls.append(kwargs)
        return type("ArtifactRef", (), {"artifact_id": f"artifact-{len(self.calls)}"})()


class FakeEventRepository:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


class TestableLabHealthService(LabHealthService):
    def _http_json(self, path):
        if path == "/v2/version":
            return {"version": "2.2-test"}
        if path == "/v2/projects":
            return [{"project_id": "project-1", "name": "WiFi-Regression-Lab", "status": "opened"}]
        if path == "/v2/projects/project-1/nodes":
            return [
                {"name": "frr-router", "status": "started"},
                {"name": "hostapd-ap", "status": "started"},
                {"name": "wifi-client", "status": "started"},
                {"name": "monitor", "status": "started"},
            ]
        raise AssertionError(path)


def make_service(tmp_path, runner=None):
    artifacts = FakeArtifactService()
    events = FakeEventRepository()
    service = TestableLabHealthService(
        run_id="run-1",
        attempt_id="attempt-1",
        local_runner=runner or FakeRunner(),
        remote_runner=runner or FakeRunner(),
        artifact_service=artifacts,
        event_repository=events,
        output_directory=tmp_path,
        resolved_config={
            "network": {"client_interface": "wlan0", "client_wifi_ip": "192.168.122.30"},
            "dns": {"test_hostname": "google.com"},
            "thresholds": {"min_free_disk_gib": 1},
        },
    )
    return service, artifacts, events


def test_lab_health_snapshot_is_healthy_and_persisted(tmp_path):
    service, artifacts, events = make_service(tmp_path)

    snapshot = service.check(phase="BEFORE")

    assert snapshot.overall_status is EnvironmentHealthStatus.HEALTHY
    assert all(item.status is HealthObservationStatus.HEALTHY for item in snapshot.observations)
    assert snapshot.snapshot_id.startswith("LABHEALTH-")
    assert len(artifacts.calls) == 1
    assert artifacts.calls[0]["artifact_type"] is ArtifactType.LAB_HEALTH_SNAPSHOT
    assert len(events.events) == 2
    assert Path(artifacts.calls[0]["path"]).exists()


def test_required_health_failure_creates_diagnostic_evidence(tmp_path):
    class FailingRunner(FakeRunner):
        def execute(self, target, command, **kwargs):
            command_text = command if isinstance(command, str) else " ".join(command)
            if target == "client_vm" and command_text.startswith("echo"):
                return CommandResult(
                    "cmd", target, "lab_health", command_text,
                    stdout="", stderr="ssh failed", exit_code=None,
                    transport="fake", transport_error="connection refused"
                )
            return super().execute(target, command, **kwargs)

    service, artifacts, events = make_service(tmp_path, FailingRunner())

    snapshot = service.check(phase="BEFORE")

    assert snapshot.overall_status is EnvironmentHealthStatus.FAILED
    artifact_types = [call["artifact_type"] for call in artifacts.calls]
    assert artifact_types == [ArtifactType.LAB_HEALTH_SNAPSHOT, ArtifactType.DIAGNOSTIC_BUNDLE]
    assert any(item.component == "management.ssh" and item.status is HealthObservationStatus.FAILED for item in snapshot.observations)
    assert any(event.event_type == "LAB_HEALTH_COMPLETED" for event in events.events)


def test_degraded_optional_health_does_not_block_run(tmp_path):
    class DegradedRunner(FakeRunner):
        def execute(self, target, command, **kwargs):
            command_text = command if isinstance(command, str) else " ".join(command)
            if target == "lab_host" and command_text.startswith("timedatectl"):
                return CommandResult(
                    "cmd", target, "lab_health", command_text,
                    stdout="no\n", exit_code=0, transport="fake"
                )
            return super().execute(target, command, **kwargs)

    service, _, _ = make_service(tmp_path, DegradedRunner())
    snapshot = service.check(phase="BEFORE")

    assert snapshot.overall_status is EnvironmentHealthStatus.DEGRADED
    clock = next(item for item in snapshot.observations if item.component == "clock")
    assert clock.status is HealthObservationStatus.DEGRADED
