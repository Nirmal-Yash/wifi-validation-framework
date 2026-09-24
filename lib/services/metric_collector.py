from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from lib.domain import DomainValidationError, Metric, Sample


class MetricCollector:
    """Collect one or more raw samples per named metric."""

    def __init__(self) -> None:
        self._metrics: dict[str, tuple[str, list[Sample]]] = {}

    def log(
        self,
        value: float,
        unit: str,
        *,
        name: str = "metric",
        warmup: bool = False,
        retried: bool = False,
        status: str = "VALID",
        metadata: Mapping[str, Any] | None = None,
        captured_at: datetime | None = None,
    ) -> None:
        if not name.strip():
            raise DomainValidationError("metric name must not be empty")
        if not unit.strip():
            raise DomainValidationError("metric unit must not be empty")
        existing = self._metrics.get(name)
        if existing is not None and existing[0] != unit:
            raise DomainValidationError(
                f"metric '{name}' cannot change unit from {existing[0]} to {unit}"
            )
        samples = existing[1] if existing else []
        samples.append(
            Sample(
                value=float(value),
                status=status,
                warmup=warmup,
                retried=retried,
                captured_at=captured_at or datetime.now(timezone.utc),
                metadata=dict(metadata or {}),
            )
        )
        self._metrics[name] = (unit, samples)

    def metrics(self) -> tuple[Metric, ...]:
        return tuple(
            Metric(name=name, unit=unit, samples=tuple(samples))
            for name, (unit, samples) in self._metrics.items()
        )

    @property
    def sample_count(self) -> int:
        return sum(len(samples) for _, samples in self._metrics.values())
