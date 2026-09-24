from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Mapping

from .command_runner import CommandRunner
from .fault_service import FaultService
from .protocol_evidence import ProtocolEvidenceService
from .wifi_telemetry import WifiTelemetryService

from .artifact_service import ArtifactService
from .run_service import RunService
from .test_registry import TestDefinition, TestRegistry


@dataclass(frozen=True, slots=True)
class RunContext:
    run_service: RunService
    run_id: str
    attempt_id: str
    lab_id: str
    device_id: str
    resolved_config: Mapping[str, Any]
    test_registry: TestRegistry
    artifact_service: ArtifactService | None = None
    command_runner: CommandRunner | None = None
    fault_service: FaultService | None = None
    protocol_evidence_service: ProtocolEvidenceService | None = None
    telemetry_service: WifiTelemetryService | None = None
    logger: logging.Logger | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("run_id", self.run_id),
            ("attempt_id", self.attempt_id),
            ("lab_id", self.lab_id),
            ("device_id", self.device_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")

    def definition_for(self, node_id: str) -> TestDefinition:
        return self.test_registry.resolve_or_fallback(node_id)
