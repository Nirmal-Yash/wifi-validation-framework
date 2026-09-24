from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True, slots=True)
class CertificationScenario:
    scenario_id: str
    name: str
    expected_lifecycle: str
    expected_outcome: str | None
    required_controls: tuple[str, ...]
    execution_class: str

CERTIFICATION_SCENARIOS: tuple[CertificationScenario, ...] = (
    CertificationScenario("healthy_run", "Healthy Run", "COMPLETED", "VALIDATED", ("required_tests","required_evidence","telemetry","regression","lineage"), "HARDWARE_FREE_PLUS_REAL_LAB"),
    CertificationScenario("product_failure", "Real product failure", "FAILED", "REJECTED", ("failure_evidence","product_statistics","complete_lifecycle"), "SIMULATED_PLUS_REAL_LAB"),
    CertificationScenario("missing_evidence", "Missing evidence", "COMPLETED", "UNVALIDATED", ("evidence_integrity","pass_blocked"), "HARDWARE_FREE"),
    CertificationScenario("lab_failure", "Lab failure", "LAB_FAILED", "UNVALIDATED", ("infra_classification","statistics_isolation","cleanup"), "HARDWARE_FREE_PLUS_REAL_LAB"),
    CertificationScenario("runner_failure", "Runner/worker failure", "ABORTED", "UNVALIDATED", ("failure_class","diagnostics","cleanup"), "HARDWARE_FREE"),
    CertificationScenario("timeout_cancellation", "Timeout and cancellation", "ABORTED_OR_CANCELLED", "UNVALIDATED", ("child_cleanup","unlock","evidence_preservation"), "HARDWARE_FREE"),
    CertificationScenario("concurrent_execution", "Concurrent execution", "QUEUED_OR_COMPLETED", None, ("exclusive_lock","no_destructive_race","consistent_state"), "HARDWARE_FREE_PLUS_REAL_LAB"),
    CertificationScenario("firmware_lifecycle", "Firmware lifecycle", "COMPLETED_OR_FAILED", None, ("integrity","authorization","state_transitions","audit"), "FAKE_ADAPTER_PLUS_PROTECTED_TARGET"),
    CertificationScenario("offline_operation", "Offline operation", "COMPLETED_OR_TERMINAL", None, ("local_authority","queue","idempotency","retry"), "HARDWARE_FREE"),
    CertificationScenario("restart_recovery", "Restart recovery", "RECOVERED", None, ("run_recovery","lock_recovery","sync_recovery"), "HARDWARE_FREE"),
    CertificationScenario("real_lab_baseline", "Protected 11-test real-lab baseline", "COMPLETED", "VALIDATED", ("pcap","protocol_evidence","telemetry","metrics","hashes","lab_health","fingerprint"), "REAL_LAB"),
)

class CertificationMatrix:
    def __init__(self, scenarios: tuple[CertificationScenario, ...] = CERTIFICATION_SCENARIOS):
        ids = [item.scenario_id for item in scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate certification scenario id")
        self.scenarios = scenarios
        self._by_id = {item.scenario_id: item for item in scenarios}
    def get(self, scenario_id: str) -> CertificationScenario:
        return self._by_id[scenario_id]
    def as_dict(self) -> dict[str, object]:
        return {"schema_version":"netregress-certification.v1","scenario_count":len(self.scenarios),"scenarios":[{"scenario_id":s.scenario_id,"name":s.name,"expected_lifecycle":s.expected_lifecycle,"expected_outcome":s.expected_outcome,"required_controls":list(s.required_controls),"execution_class":s.execution_class} for s in self.scenarios]}
    def validate_evidence(self, evidence: Mapping[str, Mapping[str, object]]) -> tuple[str, ...]:
        missing=[]
        for scenario in self.scenarios:
            record=evidence.get(scenario.scenario_id)
            if record is None:
                missing.append(scenario.scenario_id); continue
            observed=set(record.get("controls",()))
            if any(control not in observed for control in scenario.required_controls):
                missing.append(scenario.scenario_id)
        return tuple(sorted(missing))
