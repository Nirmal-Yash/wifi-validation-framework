from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Mapping

class TelemetryEnvironmentClass(str, Enum):
    """Execution environment represented by a WiFi telemetry point."""

    VIRTUAL_WIFI = "VIRTUAL_WIFI"
    PHYSICAL_WIFI = "PHYSICAL_WIFI"

class TelemetryMetric(str, Enum):
    RSSI_DBM = "rssi_dbm"
    SNR_DB = "snr_db"
    CHANNEL = "channel"
    FREQUENCY_MHZ = "frequency_mhz"
    BITRATE_MBPS = "bitrate_mbps"
    PHY_MODE = "phy_mode"
    TX_RETRIES_TOTAL = "tx_retries_total"
    TX_FAILED_TOTAL = "tx_failed_total"

@dataclass(frozen=True, slots=True)
class TelemetryPoint:
    """One observed WiFi measurement with explicit environment provenance."""

    metric: TelemetryMetric
    value: float | int | str
    unit: str
    environment_class: TelemetryEnvironmentClass
    source: str
    interface: str
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.unit.strip():
            raise ValueError("telemetry unit must not be empty")
        if not self.source.strip():
            raise ValueError("telemetry source must not be empty")
        if not self.interface.strip():
            raise ValueError("telemetry interface must not be empty")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float, str)):
            raise ValueError("telemetry value must be numeric or categorical text")
        if isinstance(self.value, (int, float)) and not math.isfinite(float(self.value)):
            raise ValueError("telemetry numeric value must be finite")
        if self.captured_at.tzinfo is None:
            raise ValueError("telemetry timestamp must be timezone-aware")

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric.value,
            "value": self.value,
            "unit": self.unit,
            "environment_class": self.environment_class.value,
            "source": self.source,
            "interface": self.interface,
            "captured_at": self.captured_at.isoformat(),
            "metadata": dict(self.metadata),
        }

@dataclass(frozen=True, slots=True)
class WifiTelemetrySnapshot:
    """Immutable Run-scoped telemetry sample set."""

    snapshot_id: str
    run_id: str
    target: str
    interface: str
    environment_class: TelemetryEnvironmentClass
    captured_at: datetime
    points: tuple[TelemetryPoint, ...]
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("snapshot_id", self.snapshot_id),
            ("run_id", self.run_id),
            ("target", self.target),
            ("interface", self.interface),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not self.points:
            raise ValueError("telemetry snapshot must contain at least one point")
        if self.captured_at.tzinfo is None:
            raise ValueError("telemetry snapshot timestamp must be timezone-aware")
        metrics = [point.metric for point in self.points]
        if len(metrics) != len(set(metrics)):
            raise ValueError("telemetry snapshot must not contain duplicate metrics")
        if any(
            point.environment_class != self.environment_class
            or point.interface != self.interface
            for point in self.points
        ):
            raise ValueError("every telemetry point must match the snapshot environment class and interface")

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "target": self.target,
            "interface": self.interface,
            "environment_class": self.environment_class.value,
            "captured_at": self.captured_at.isoformat(),
            "points": [point.as_dict() for point in self.points],
            "warnings": list(self.warnings),
        }
