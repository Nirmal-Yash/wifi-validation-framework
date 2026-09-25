from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any, Mapping
import urllib.error
import urllib.request
import uuid

from lib.domain import (
    ArtifactType,
    EnvironmentHealthStatus,
    HealthObservation,
    HealthObservationStatus,
    LabHealthSnapshot,
    LifecycleEvent,
)
from lib.services.command_runner import CommandRunner, CommandResult
from lib.services.command_security import redact_text
from lib.services.artifact_service import ArtifactService


class LabHealthService:
    """Read-only lab health diagnosis with Run-scoped evidence."""

    REQUIRED_GNS3_NODES = ("frr-router", "hostapd-ap", "wifi-client", "monitor")
    REMOTE_TARGETS = {
        "ap": "ap_host",
        "client": "client_vm",
        "router": "router1",
        "monitor": "monitor_vm",
    }

    def __init__(
        self,
        *,
        run_id: str,
        attempt_id: str,
        local_runner: CommandRunner,
        remote_runner: CommandRunner,
        artifact_service: ArtifactService,
        event_repository: Any,
        output_directory: str | Path,
        resolved_config: Mapping[str, Any],
        gns3_api: str = "http://127.0.0.1:3080",
        gns3_project_name: str = "WiFi-Regression-Lab",
        gns3_timeout_sec: float = 5.0,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.local_runner = local_runner
        self.remote_runner = remote_runner
        self.artifact_service = artifact_service
        self.event_repository = event_repository
        self.output_directory = Path(output_directory)
        self.resolved_config = resolved_config
        self.gns3_api = gns3_api.rstrip("/")
        self.gns3_project_name = gns3_project_name
        self.gns3_timeout_sec = gns3_timeout_sec
        self.clock = clock

    def check(self, *, phase: str) -> LabHealthSnapshot:
        started = self.clock()
        self._event("LAB_HEALTH_STARTED", started, {"phase": phase})
        observations: list[HealthObservation] = []

        checks = (
            ("gns3", self._check_gns3, True),
            ("docker", lambda: self._check_local_command(
                "docker info --format {{.ServerVersion}}", "Docker service reachable"
            ), True),
            ("libvirt", lambda: self._check_local_command(
                "virsh net-info default", "libvirt default network reachable"
            ), True),
            ("hwsim", lambda: self._check_local_hwsim(), True),
            ("management.ssh", self._check_management_ssh, True),
            ("ap", lambda: self._check_remote(
                "ap", "echo NETREGRESS_HEALTH_OK", "AP SSH execution reachable"
            ), True),
            ("client", lambda: self._check_remote(
                "client", "ip link show wlan0", "client wlan0 exists"
            ), True),
            ("router", lambda: self._check_remote(
                "router", "ip link show eth1", "router eth1 exists"
            ), True),
            ("monitor", lambda: self._check_remote(
                "monitor", "ip link show eth0", "monitor eth0 exists"
            ), True),
            ("dhcp", self._check_dhcp, True),
            ("dns", self._check_dns, True),
            ("iperf3", self._check_iperf3, True),
            ("disk", self._check_disk, False),
            ("clock", self._check_clock, False),
        )

        for component, checker, required in checks:
            try:
                status, duration_ms, summary, details, tool_metadata = checker()
            except Exception as exc:
                status = HealthObservationStatus.UNKNOWN
                duration_ms = 0
                safe_error, _ = redact_text(f"{type(exc).__name__}: {exc}")
                summary = f"Health check could not be completed: {safe_error}"
                details = {"exception": safe_error}
                tool_metadata = {}
            observations.append(
                HealthObservation(
                    component=component,
                    status=status,
                    duration_ms=duration_ms,
                    summary=summary,
                    observed_at=self.clock(),
                    details=details,
                    required=required,
                    tool_metadata=tool_metadata,
                )
            )

        overall = self._rollup(observations)
        completed = self.clock()
        snapshot = LabHealthSnapshot(
            snapshot_id=f"LABHEALTH-{uuid.uuid4().hex[:16]}",
            run_id=self.run_id,
            phase=phase,
            overall_status=overall,
            observations=tuple(observations),
            started_at=started,
            completed_at=completed,
        )
        artifact_path = self._write_snapshot(snapshot)
        artifact = self.artifact_service.register_file(
            run_id=self.run_id,
            path=artifact_path,
            artifact_type=ArtifactType.LAB_HEALTH_SNAPSHOT,
            display_name=f"lab-health-{phase.lower()}-{self.run_id}.json",
            sensitivity_class="INTERNAL",
        )

        if snapshot.unhealthy:
            diagnostic_path = self._write_diagnostic_bundle(snapshot)
            self.artifact_service.register_file(
                run_id=self.run_id,
                path=diagnostic_path,
                artifact_type=ArtifactType.DIAGNOSTIC_BUNDLE,
                display_name=f"lab-health-diagnostic-{phase.lower()}-{self.run_id}.json",
                sensitivity_class="SENSITIVE",
            )

        self._event(
            "LAB_HEALTH_COMPLETED",
            completed,
            {
                "phase": phase,
                "overall_status": snapshot.overall_status.value,
                "snapshot_id": snapshot.snapshot_id,
                "artifact_id": artifact.artifact_id,
                "failed_components": [
                    item.component
                    for item in snapshot.observations
                    if item.status == HealthObservationStatus.FAILED
                ],
                "degraded_components": [
                    item.component
                    for item in snapshot.observations
                    if item.status == HealthObservationStatus.DEGRADED
                ],
                "unknown_components": [
                    item.component
                    for item in snapshot.observations
                    if item.status == HealthObservationStatus.UNKNOWN
                ],
            },
        )
        return snapshot

    def _check_gns3(self):
        started = time.monotonic()
        try:
            version = self._http_json("/v2/version")
            projects = self._http_json("/v2/projects")
        except Exception as exc:
            duration = int((time.monotonic() - started) * 1000)
            safe_error, _ = redact_text(f"{type(exc).__name__}: {exc}")
            return (
                HealthObservationStatus.FAILED,
                duration,
                f"GNS3 API is unreachable or unauthorized: {safe_error}",
                {"endpoint": self.gns3_api, "error": safe_error},
                {},
            )

        project = next(
            (item for item in projects if item.get("name") == self.gns3_project_name),
            None,
        )
        if project is None:
            duration = int((time.monotonic() - started) * 1000)
            return (
                HealthObservationStatus.FAILED,
                duration,
                f"Required GNS3 project '{self.gns3_project_name}' was not found",
                {
                    "project": self.gns3_project_name,
                    "available_projects": [item.get("name") for item in projects],
                },
                {"gns3_version": str(version.get("version", "unknown"))},
            )

        project_id = project.get("project_id")
        nodes = self._http_json(f"/v2/projects/{project_id}/nodes")
        node_map = {item.get("name"): item for item in nodes}
        missing = [name for name in self.REQUIRED_GNS3_NODES if name not in node_map]
        stopped = [
            name
            for name in self.REQUIRED_GNS3_NODES
            if name in node_map and node_map[name].get("status") not in {"started", "running"}
        ]
        duration = int((time.monotonic() - started) * 1000)
        if missing:
            return (
                HealthObservationStatus.FAILED,
                duration,
                f"GNS3 project is missing required nodes: {missing}",
                {"project_id": project_id, "missing_nodes": missing},
                {"gns3_version": str(version.get("version", "unknown"))},
            )
        if stopped:
            return (
                HealthObservationStatus.FAILED,
                duration,
                f"GNS3 required nodes are not started: {stopped}",
                {"project_id": project_id, "stopped_nodes": stopped},
                {"gns3_version": str(version.get("version", "unknown"))},
            )
        return (
            HealthObservationStatus.HEALTHY,
            duration,
            "GNS3 API, project and required nodes are healthy",
            {
                "project_id": project_id,
                "project_status": project.get("status"),
                "node_count": len(nodes),
            },
            {"gns3_version": str(version.get("version", "unknown"))},
        )

    def _http_json(self, path: str) -> Mapping[str, Any] | list[Mapping[str, Any]]:
        url = f"{self.gns3_api}{path}"
        request = urllib.request.Request(url, method="GET")
        user, password = self._gns3_credentials()
        if user and password:
            import base64
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            request.add_header("Authorization", f"Basic {token}")
        with urllib.request.urlopen(request, timeout=self.gns3_timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _gns3_credentials() -> tuple[str | None, str | None]:
        import os

        user = os.getenv("GNS3_API_USER")
        password = os.getenv("GNS3_API_PASSWORD")
        if user and password:
            return user, password

        candidates = (
            Path.home() / ".config" / "GNS3" / "2.2" / "gns3_server.conf",
            Path("/root/.config/GNS3/2.2/gns3_server.conf"),
        )
        for path in candidates:
            try:
                if not path.is_file():
                    continue
                values: dict[str, str] = {}
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    key, separator, value = line.partition("=")
                    if separator and key.strip() in {"user", "password"}:
                        values[key.strip()] = value.strip()
                if values.get("user") and values.get("password"):
                    return values["user"], values["password"]
            except OSError:
                continue
        return None, None

    def _check_local_command(self, command: str, summary: str):
        started = time.monotonic()
        result = self.local_runner.execute("lab_host", command)
        duration = int((time.monotonic() - started) * 1000)
        if result.transport_error or not result.stdout.strip():
            return (
                HealthObservationStatus.FAILED,
                duration,
                f"{summary} failed: {result.transport_error}",
                {"stdout": result.stdout, "stderr": result.stderr},
                {"transport": result.transport},
            )
        if result.exit_code not in {None, 0}:
            return (
                HealthObservationStatus.FAILED,
                duration,
                f"{summary} failed with exit code {result.exit_code}",
                {"stdout": result.stdout, "stderr": result.stderr},
                {"transport": result.transport},
            )
        return (
            HealthObservationStatus.HEALTHY,
            duration,
            summary,
            {"stdout": result.stdout.strip()[:1000]},
            {"transport": result.transport},
        )

    def _check_local_hwsim(self):
        started = time.monotonic()
        results = {}
        failures = []
        for role in ("ap", "client"):
            target = self.REMOTE_TARGETS[role]
            result = self.remote_runner.execute(
                target,
                ["iw", "phy"],
                command_category="lab_health",
                idempotent=True,
            )
            phys = re.findall(r"(?m)^Wiphy\s+(\S+)", result.stdout)
            results[role] = {
                "phys": phys,
                "error": result.transport_error,
            }
            if result.transport_error or result.exit_code not in {None, 0} or len(phys) < 1:
                failures.append(role)

        duration = int((time.monotonic() - started) * 1000)
        if failures:
            return (
                HealthObservationStatus.FAILED,
                duration,
                f"mac80211_hwsim PHY validation failed for: {failures}",
                results,
                {"transport": "command_runner"},
            )
        return (
            HealthObservationStatus.HEALTHY,
            duration,
            "AP and client namespaces each expose at least one wireless PHY",
            results,
            {"transport": "command_runner"},
        )

    def _check_management_ssh(self):
        started = time.monotonic()
        failures: list[str] = []
        targets = ("client", "ap", "router", "monitor")
        for target in targets:
            result = self.remote_runner.execute(
                self.REMOTE_TARGETS[target],
                "echo NETREGRESS_HEALTH_OK",
                command_category="lab_health",
                idempotent=True,
            )
            if result.transport_error or "NETREGRESS_HEALTH_OK" not in result.stdout:
                failures.append(
                    f"{target}: {result.transport_error or result.stdout.strip() or 'no response'}"
                )
        duration = int((time.monotonic() - started) * 1000)
        if failures:
            return (
                HealthObservationStatus.FAILED,
                duration,
                "One or more management SSH targets are unavailable",
                {"failures": failures},
                {"transport": "command_runner"},
            )
        return (
            HealthObservationStatus.HEALTHY,
            duration,
            "All required management SSH paths are reachable",
            {"targets": list(targets)},
            {"transport": "command_runner"},
        )

    def _check_remote(self, role: str, command: str, summary: str):
        started = time.monotonic()
        target = self.REMOTE_TARGETS[role]
        result = self.remote_runner.execute(
            target,
            command,
            command_category="lab_health",
            idempotent=True,
        )
        duration = int((time.monotonic() - started) * 1000)
        if result.transport_error:
            return (
                HealthObservationStatus.FAILED,
                duration,
                f"{summary} failed: {result.transport_error}",
                {"output": result.stdout, "error": result.transport_error},
                {"transport": result.transport},
            )
        if result.exit_code not in {None, 0}:
            return (
                HealthObservationStatus.FAILED,
                duration,
                f"{summary} failed with exit code {result.exit_code}",
                {"output": result.stdout},
                {"transport": result.transport},
            )
        return (
            HealthObservationStatus.HEALTHY,
            duration,
            summary,
            {"output": result.stdout.strip()[:1200]},
            {"transport": result.transport},
        )

    def _check_dhcp(self):
        iface = self.resolved_config.get("network", {}).get("client_interface", "wlan0")
        expected = self.resolved_config.get("network", {}).get("client_wifi_ip", "")
        started = time.monotonic()
        result = self.remote_runner.execute(
            self.REMOTE_TARGETS["client"],
            ["ip", "-4", "addr", "show", iface],
            command_category="lab_health",
            idempotent=True,
        )
        duration = int((time.monotonic() - started) * 1000)
        matched = bool(
            expected
            and (
                f"inet {expected}/" in result.stdout
                or f"inet {expected} " in result.stdout
            )
        )
        if result.transport_error or result.exit_code not in {None, 0} or not matched:
            return (
                HealthObservationStatus.FAILED,
                duration,
                "Client does not hold the expected DHCP WiFi address",
                {
                    "interface": iface,
                    "expected_ip": expected,
                    "output": result.stdout,
                    "error": result.transport_error,
                },
                {"transport": result.transport},
            )
        return (
            HealthObservationStatus.HEALTHY,
            duration,
            "Expected DHCP lease is present on the client WiFi interface",
            {"interface": iface, "address": expected},
            {"transport": result.transport},
        )

    def _check_dns(self):
        hostname = self.resolved_config.get("dns", {}).get("test_hostname", "google.com")
        started = time.monotonic()
        result = self.remote_runner.execute(
            self.REMOTE_TARGETS["client"],
            ["nslookup", hostname],
            command_category="lab_health",
            idempotent=True,
        )
        duration = int((time.monotonic() - started) * 1000)
        lowered = result.stdout.lower()
        resolved = "address:" in lowered and "can't find" not in lowered
        if result.transport_error or result.exit_code not in {None, 0} or not resolved:
            return (
                HealthObservationStatus.FAILED,
                duration,
                f"DNS resolution failed for {hostname}",
                {"hostname": hostname, "output": result.stdout, "error": result.transport_error},
                {"transport": result.transport},
            )
        return (
            HealthObservationStatus.HEALTHY,
            duration,
            f"DNS resolution succeeded for {hostname}",
            {"hostname": hostname},
            {"transport": result.transport},
        )

    def _check_iperf3(self):
        started = time.monotonic()
        result = self.remote_runner.execute(
            self.REMOTE_TARGETS["router"],
            ["pgrep", "iperf3"],
            command_category="lab_health",
            idempotent=True,
        )
        duration = int((time.monotonic() - started) * 1000)
        if result.transport_error or result.exit_code not in {None, 0} or not result.stdout.strip():
            return (
                HealthObservationStatus.FAILED,
                duration,
                "iperf3 server process is not running on the router",
                {"output": result.stdout, "error": result.transport_error},
                {"transport": result.transport},
            )
        return (
            HealthObservationStatus.HEALTHY,
            duration,
            "iperf3 server is running on the router",
            {"process_ids": result.stdout.split()},
            {"transport": result.transport},
        )

    def _check_disk(self):
        result = self.local_runner.execute(
            "lab_host",
            ["df", "-Pk", str(self.output_directory)],
            command_category="lab_health",
            idempotent=True,
        )
        duration = result.duration_ms
        if result.transport_error or result.exit_code != 0:
            return (
                HealthObservationStatus.DEGRADED,
                duration,
                "Unable to determine free disk capacity",
                {"output": result.stdout, "error": result.transport_error},
                {"transport": result.transport},
            )
        values = result.stdout.strip().splitlines()
        if len(values) < 2:
            return (
                HealthObservationStatus.DEGRADED,
                duration,
                "Disk capacity output could not be parsed",
                {"output": result.stdout},
                {"transport": result.transport},
            )
        parts = values[-1].split()
        try:
            available_kib = int(parts[3])
            available_gib = round(available_kib / (1024 * 1024), 2)
        except (IndexError, ValueError):
            return (
                HealthObservationStatus.DEGRADED,
                duration,
                "Disk capacity output could not be parsed",
                {"output": result.stdout},
                {"transport": result.transport},
            )
        min_gib = float(
            self.resolved_config.get("thresholds", {}).get("min_free_disk_gib", 2)
        )
        status = (
            HealthObservationStatus.HEALTHY
            if available_gib >= min_gib
            else HealthObservationStatus.DEGRADED
        )
        return (
            status,
            duration,
            f"{available_gib} GiB free at health-check path",
            {"available_gib": available_gib, "minimum_gib": min_gib},
            {"transport": result.transport},
        )

    def _check_clock(self):
        started = time.monotonic()
        result = self.local_runner.execute(
            "lab_host",
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            command_category="lab_health",
            idempotent=True,
        )
        duration = result.duration_ms
        if result.transport_error or result.exit_code != 0:
            return (
                HealthObservationStatus.UNKNOWN,
                duration,
                "Clock synchronization could not be determined",
                {"output": result.stdout, "error": result.transport_error},
                {"transport": result.transport},
            )
        synchronized = result.stdout.strip().lower() == "yes"
        return (
            HealthObservationStatus.HEALTHY if synchronized else HealthObservationStatus.DEGRADED,
            duration,
            "Host clock is synchronized" if synchronized else "Host clock is not synchronized",
            {"ntp_synchronized": synchronized},
            {"transport": result.transport},
        )

    @staticmethod
    def _rollup(observations: list[HealthObservation]) -> EnvironmentHealthStatus:
        statuses = [item.status for item in observations]
        if any(item.status == HealthObservationStatus.FAILED and item.required for item in observations):
            return EnvironmentHealthStatus.FAILED
        if any(item.status == HealthObservationStatus.DEGRADED for item in observations):
            return EnvironmentHealthStatus.DEGRADED
        if any(item.status == HealthObservationStatus.UNKNOWN for item in observations):
            return EnvironmentHealthStatus.DEGRADED
        if any(item.status == HealthObservationStatus.FAILED for item in observations):
            return EnvironmentHealthStatus.DEGRADED
        return EnvironmentHealthStatus.HEALTHY

    def _write_snapshot(self, snapshot: LabHealthSnapshot) -> Path:
        self.output_directory.mkdir(parents=True, exist_ok=True)
        path = self.output_directory / (
            f"lab-health-{snapshot.phase.lower()}-{self.run_id}.json"
        )
        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "run_id": snapshot.run_id,
            "attempt_id": self.attempt_id,
            "phase": snapshot.phase,
            "overall_status": snapshot.overall_status.value,
            "started_at": snapshot.started_at.isoformat(),
            "completed_at": snapshot.completed_at.isoformat(),
            "observations": [
                {
                    **asdict(observation),
                    "status": observation.status.value,
                    "observed_at": observation.observed_at.isoformat(),
                }
                for observation in snapshot.observations
            ],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def _write_diagnostic_bundle(self, snapshot: LabHealthSnapshot) -> Path:
        path = self.output_directory / (
            f"lab-health-diagnostic-{snapshot.phase.lower()}-{self.run_id}.json"
        )
        failures = [
            {
                "component": observation.component,
                "status": observation.status.value,
                "summary": observation.summary,
                "details": observation.details,
                "tool_metadata": observation.tool_metadata,
            }
            for observation in snapshot.observations
            if observation.status != HealthObservationStatus.HEALTHY
        ]
        path.write_text(
            json.dumps(
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "run_id": snapshot.run_id,
                    "phase": snapshot.phase,
                    "overall_status": snapshot.overall_status.value,
                    "diagnostics": failures,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return path

    def _event(self, event_type: str, occurred_at: datetime, details: Mapping[str, Any]):
        self.event_repository.append(
            LifecycleEvent(
                event_id=uuid.uuid4().hex,
                run_id=self.run_id,
                attempt_id=self.attempt_id,
                event_type=event_type,
                occurred_at=occurred_at,
                details=details,
            )
        )
