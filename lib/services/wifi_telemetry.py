from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
import uuid

from lib.domain import ArtifactType
from lib.domain.telemetry import (
    TelemetryEnvironmentClass,
    TelemetryMetric,
    TelemetryPoint,
    WifiTelemetrySnapshot,
)
from .artifact_service import ArtifactService
from .command_runner import CommandRunner

class TelemetryCollectionError(RuntimeError):
    """Raised when no trustworthy WiFi telemetry can be collected."""

@dataclass(frozen=True, slots=True)
class _CommandObservation:
    source: str
    stdout: str
    warning: str | None = None

class WifiTelemetryService:
    """Collect read-only WiFi telemetry through the secured CommandRunner."""

    _INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")

    def __init__(
        self,
        *,
        command_runner: CommandRunner,
        target: str,
        environment_class: TelemetryEnvironmentClass,
        output_directory: str | Path = "results/telemetry",
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.command_runner = command_runner
        self.target = target
        self.environment_class = environment_class
        self.output_directory = Path(output_directory)
        self.clock = clock

    @classmethod
    def _validate_interface(cls, interface: str) -> str:
        if not cls._INTERFACE_RE.fullmatch(interface):
            raise ValueError(f"invalid WiFi interface name: {interface!r}")
        return interface

    @staticmethod
    def _key_values(output: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip().upper()] = value.strip()
        return values

    @staticmethod
    def _first_float(output: str, pattern: str) -> float | None:
        match = re.search(pattern, output, flags=re.IGNORECASE | re.MULTILINE)
        if not match:
            return None
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first_int(output: str, pattern: str) -> int | None:
        match = re.search(pattern, output, flags=re.IGNORECASE | re.MULTILINE)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bitrate_mbps(value: float, unit: str) -> float:
        if unit.lower().startswith("g"):
            return value * 1000.0
        if unit.lower().startswith("k"):
            return value / 1000.0
        return value

    @classmethod
    def parse_signal_poll(cls, output: str) -> dict[str, float]:
        fields = cls._key_values(output)
        result: dict[str, float] = {}
        for key in ("RSSI", "NOISE", "LINKSPEED", "FREQUENCY"):
            if key not in fields:
                continue
            try:
                result[key] = float(fields[key])
            except ValueError:
                continue
        return result

    @classmethod
    def parse_iw_link(cls, output: str) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        connected = re.search(
            r"^Connected to ([0-9a-f:]{17})",
            output,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if connected:
            parsed["bssid"] = connected.group(1).lower()
        ssid = re.search(r"^\s*SSID:\s*(.+?)\s*$", output, flags=re.MULTILINE)
        if ssid:
            parsed["ssid"] = ssid.group(1)
        frequency = cls._first_float(output, r"^\s*freq:\s*([0-9.]+)")
        signal = cls._first_float(output, r"^\s*signal:\s*(-?[0-9.]+)\s*dBm")
        if frequency is not None:
            parsed["frequency_mhz"] = frequency
        if signal is not None:
            parsed["signal_dbm"] = signal

        bitrate = re.search(
            r"^\s*tx bitrate:\s*([0-9.]+)\s*([GMK]?Bit/s)(.*)$",
            output,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if bitrate:
            parsed["tx_bitrate_mbps"] = cls._bitrate_mbps(float(bitrate.group(1)), bitrate.group(2))
            parsed["phy_mode"] = cls.phy_mode_from_text(bitrate.group(3))
        return parsed

    @classmethod
    def parse_station_dump(cls, output: str) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        signal = cls._first_float(output, r"^\s*signal:\s*(-?[0-9.]+)\s*dBm")
        tx_retries = cls._first_int(output, r"^\s*tx retries:\s*(\d+)")
        tx_failed = cls._first_int(output, r"^\s*tx failed:\s*(\d+)")
        tx_bitrate = re.search(
            r"^\s*tx bitrate:\s*([0-9.]+)\s*([GMK]?Bit/s)(.*)$",
            output,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        rx_bitrate = re.search(
            r"^\s*rx bitrate:\s*([0-9.]+)\s*([GMK]?Bit/s)",
            output,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if signal is not None:
            parsed["signal_dbm"] = signal
        if tx_retries is not None:
            parsed["tx_retries_total"] = tx_retries
        if tx_failed is not None:
            parsed["tx_failed_total"] = tx_failed
        if tx_bitrate:
            parsed["tx_bitrate_mbps"] = cls._bitrate_mbps(float(tx_bitrate.group(1)), tx_bitrate.group(2))
            parsed["phy_mode"] = cls.phy_mode_from_text(tx_bitrate.group(3))
        if rx_bitrate:
            parsed["rx_bitrate_mbps"] = cls._bitrate_mbps(float(rx_bitrate.group(1)), rx_bitrate.group(2))
        return parsed

    @staticmethod
    def channel_from_frequency(frequency_mhz: float) -> int | None:
        frequency = int(round(frequency_mhz))
        if frequency == 2484:
            return 14
        if 2412 <= frequency <= 2472 and (frequency - 2407) % 5 == 0:
            return (frequency - 2407) // 5
        if 5005 <= frequency <= 5895 and (frequency - 5000) % 5 == 0:
            return (frequency - 5000) // 5
        if 5955 <= frequency <= 7115 and (frequency - 5950) % 5 == 0:
            return (frequency - 5950) // 5
        return None

    @staticmethod
    def phy_mode_from_text(text: str) -> str | None:
        upper = text.upper()
        for token, label in (
            ("EHT", "802.11be (EHT)"),
            ("HE", "802.11ax (HE)"),
            ("VHT", "802.11ac (VHT)"),
            ("HT", "802.11n (HT)"),
            ("ERP", "802.11g (ERP)"),
            ("CCK", "802.11b (CCK)"),
            ("OFDM", "802.11a/g (OFDM)"),
        ):
            if token in upper:
                return label
        return None

    def _run_readonly(self, *, source: str, command: str) -> _CommandObservation:
        result = self.command_runner.execute(
            self.target,
            command,
            command_category="wifi_telemetry",
            idempotent=True,
            privilege_mode="USER",
        )
        if not result.transport_succeeded:
            return _CommandObservation(
                source=source,
                stdout="",
                warning=f"{source} transport failed: {result.transport_error}",
            )
        if result.exit_code not in (None, 0):
            return _CommandObservation(
                source=source,
                stdout=result.stdout,
                warning=f"{source} exited with code {result.exit_code}",
            )
        if not result.stdout.strip():
            return _CommandObservation(
                source=source,
                stdout="",
                warning=f"{source} returned no telemetry output",
            )
        return _CommandObservation(source=source, stdout=result.stdout)

    def capture(self, *, run_id: str, interface: str = "wlan0") -> WifiTelemetrySnapshot:
        interface = self._validate_interface(interface)
        captured_at = self.clock()
        observations = (
            self._run_readonly(
                source="wpa_cli.signal_poll",
                command=f"wpa_cli -i {interface} signal_poll",
            ),
            self._run_readonly(
                source="iw.link",
                command=f"iw dev {interface} link",
            ),
            self._run_readonly(
                source="iw.station_dump",
                command=f"iw dev {interface} station dump",
            ),
        )
        warnings = [item.warning for item in observations if item.warning]
        signal_poll = self.parse_signal_poll(observations[0].stdout)
        iw_link = self.parse_iw_link(observations[1].stdout)
        station = self.parse_station_dump(observations[2].stdout)

        signal_dbm = signal_poll.get("RSSI")
        signal_source = "wpa_cli.signal_poll"
        if signal_dbm is None:
            signal_dbm = iw_link.get("signal_dbm", station.get("signal_dbm"))
            signal_source = "iw.link" if "signal_dbm" in iw_link else "iw.station_dump"
        noise_dbm = signal_poll.get("NOISE")
        frequency_mhz = signal_poll.get("FREQUENCY")
        if frequency_mhz is None:
            frequency_mhz = iw_link.get("frequency_mhz")
        bitrate_mbps = signal_poll.get("LINKSPEED")
        bitrate_source = "wpa_cli.signal_poll"
        if bitrate_mbps is None:
            bitrate_mbps = station.get("tx_bitrate_mbps", iw_link.get("tx_bitrate_mbps"))
            bitrate_source = "iw.station_dump" if "tx_bitrate_mbps" in station else "iw.link"
        phy_mode = station.get("phy_mode") or iw_link.get("phy_mode")
        if not phy_mode:
            warnings.append("PHY mode could not be determined from observed driver output")

        points: list[TelemetryPoint] = []
        point_specs = (
            (TelemetryMetric.RSSI_DBM, signal_dbm, "dBm", signal_source),
            (TelemetryMetric.SNR_DB, signal_dbm - noise_dbm if signal_dbm is not None and noise_dbm is not None else None, "dB", signal_source),
            (TelemetryMetric.CHANNEL, self.channel_from_frequency(frequency_mhz) if frequency_mhz is not None else None, "channel", "derived.frequency_to_channel"),
            (TelemetryMetric.FREQUENCY_MHZ, frequency_mhz, "MHz", "wpa_cli.signal_poll/iw.link"),
            (TelemetryMetric.BITRATE_MBPS, bitrate_mbps, "Mbps", bitrate_source),
            (TelemetryMetric.PHY_MODE, phy_mode, "mode", "iw.link/iw.station_dump"),
            (TelemetryMetric.TX_RETRIES_TOTAL, station.get("tx_retries_total"), "count", "iw.station_dump"),
            (TelemetryMetric.TX_FAILED_TOTAL, station.get("tx_failed_total"), "count", "iw.station_dump"),
        )
        for metric, value, unit, source in point_specs:
            if value is None:
                warnings.append(f"telemetry field unavailable: {metric.value}")
                continue
            points.append(
                TelemetryPoint(
                    metric=metric,
                    value=value,
                    unit=unit,
                    environment_class=self.environment_class,
                    source=source,
                    interface=interface,
                    captured_at=captured_at,
                    metadata={"target": self.target},
                )
            )
        if not points:
            raise TelemetryCollectionError(
                f"no trustworthy WiFi telemetry collected for {self.target}:{interface}"
            )
        return WifiTelemetrySnapshot(
            snapshot_id=uuid.uuid4().hex,
            run_id=run_id,
            target=self.target,
            interface=interface,
            environment_class=self.environment_class,
            captured_at=captured_at,
            points=tuple(points),
            warnings=tuple(warnings),
        )

    @staticmethod
    def write_json(snapshot: WifiTelemetrySnapshot, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(snapshot.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return destination

    def capture_and_register(self, *, run_id: str, artifact_service: ArtifactService, interface: str = "wlan0") -> tuple[WifiTelemetrySnapshot, Any]:
        snapshot = self.capture(run_id=run_id, interface=interface)
        self.output_directory.mkdir(parents=True, exist_ok=True)
        safe_interface = re.sub(r"[^A-Za-z0-9_.:-]+", "_", interface)
        path = self.output_directory / f"{run_id}-{safe_interface}.json"
        self.write_json(snapshot, path)
        artifact = artifact_service.register_file(
            run_id=run_id,
            path=path,
            artifact_type=ArtifactType.TELEMETRY,
            display_name=f"wifi-telemetry-{run_id}-{safe_interface}.json",
            sensitivity_class="INTERNAL",
        )
        return snapshot, artifact
