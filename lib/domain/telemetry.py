from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from types import MappingProxyType
from typing import Any


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


def _freeze_json(value: Any, *, path: str = "metadata") -> Any:
    """Detach and recursively freeze JSON-compatible telemetry metadata."""
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            frozen[key] = _freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, path=f"{path}[{i}]") for i, item in enumerate(value))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError(f"{path} must contain only finite JSON-compatible values")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


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
        if not isinstance(self.metric, TelemetryMetric):
            raise ValueError("telemetry metric must be a TelemetryMetric")
        if not isinstance(self.environment_class, TelemetryEnvironmentClass):
            raise ValueError("telemetry environment_class must be explicit")
        for name, value in (("unit", self.unit), ("source", self.source), ("interface", self.interface)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"telemetry {name} must not be empty")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float, str)):
            raise ValueError("telemetry value must be numeric or categorical text")
        if isinstance(self.value, (int, float)) and not math.isfinite(float(self.value)):
            raise ValueError("telemetry numeric value must be finite")
        if isinstance(self.value, str) and not self.value.strip():
            raise ValueError("telemetry text value must not be empty")
        if not isinstance(self.captured_at, datetime) or self.captured_at.tzinfo is None:
            raise ValueError("telemetry timestamp must be timezone-aware")
        if self.captured_at.utcoffset() is None:
            raise ValueError("telemetry timestamp must have a UTC offset")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("telemetry metadata must be a mapping")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric.value,
            "value": self.value,
            "unit": self.unit,
            "environment_class": self.environment_class.value,
            "source": self.source,
            "interface": self.interface,
            "captured_at": self.captured_at.isoformat(),
            "metadata": _thaw_json(self.metadata),
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
        for name, value in (("snapshot_id", self.snapshot_id), ("run_id", self.run_id),
                            ("target", self.target), ("interface", self.interface)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not isinstance(self.environment_class, TelemetryEnvironmentClass):
            raise ValueError("snapshot environment_class must be explicit")
        if not isinstance(self.captured_at, datetime) or self.captured_at.tzinfo is None:
            raise ValueError("telemetry snapshot timestamp must be timezone-aware")
        if self.captured_at.utcoffset() is None:
            raise ValueError("telemetry snapshot timestamp must have a UTC offset")
        points = tuple(self.points)
        if not points or any(not isinstance(point, TelemetryPoint) for point in points):
            raise ValueError("telemetry snapshot must contain TelemetryPoint values")
        metrics = [point.metric for point in points]
        if len(metrics) != len(set(metrics)):
            raise ValueError("telemetry snapshot must not contain duplicate metrics")
        if any(point.environment_class != self.environment_class or point.interface != self.interface
               for point in points):
            raise ValueError("every telemetry point must match the snapshot environment class and interface")
        warnings = tuple(self.warnings)
        if any(not isinstance(item, str) or not item.strip() for item in warnings):
            raise ValueError("telemetry warnings must be non-empty strings")
        object.__setattr__(self, "points", points)
        object.__setattr__(self, "warnings", warnings)

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
