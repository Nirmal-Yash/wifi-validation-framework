from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping
from lib.domain import FailureClass, RunLifecycle

class InjectionResult(str, Enum):
    EXPECTED_FAILURE = "EXPECTED_FAILURE"
    IDEMPOTENT_NOOP = "IDEMPOTENT_NOOP"

@dataclass(frozen=True, slots=True)
class FailureInjectionCase:
    case_id: str
    category: str
    expected_failure: FailureClass | None
    expected_lifecycle: RunLifecycle | None
    requires_cleanup: bool = True
    isolates_product_statistics: bool = True
    expected_idempotent: bool = False

@dataclass(frozen=True, slots=True)
class FailureInjectionObservation:
    case_id: str
    result: InjectionResult
    failure_class: FailureClass | None
    lifecycle: RunLifecycle | None
    cleanup_ok: bool
    artifacts_preserved: bool
    lock_recovered: bool
    statistics_isolated: bool
    diagnosable: bool
    @property
    def passed(self) -> bool:
        expected = FAILURE_INJECTION_CASES[self.case_id]
        result_ok = (
            self.result is InjectionResult.IDEMPOTENT_NOOP
            if expected.expected_idempotent
            else self.result is InjectionResult.EXPECTED_FAILURE
        )
        failure_ok = expected.expected_failure is None or self.failure_class is expected.expected_failure
        lifecycle_ok = expected.expected_lifecycle is None or self.lifecycle is expected.expected_lifecycle
        return result_ok and failure_ok and lifecycle_ok and self.cleanup_ok and self.artifacts_preserved and self.lock_recovered and self.statistics_isolated and self.diagnosable

def _case(case_id: str, category: str, failure: FailureClass | None = FailureClass.LAB_FAILED, lifecycle: RunLifecycle | None = RunLifecycle.LAB_FAILED, *, idempotent: bool = False) -> FailureInjectionCase:
    return FailureInjectionCase(case_id, category, failure, lifecycle, expected_idempotent=idempotent)

FAILURE_INJECTION_CASES: Mapping[str, FailureInjectionCase] = {
    c.case_id: c for c in (
        _case("ssh_timeout", "device"),
        _case("device_unavailable", "device"),
        _case("dut_restart_crash", "device", FailureClass.PRODUCT_FAILED, RunLifecycle.FAILED),
        _case("dhcp_failure", "protocol"),
        _case("dhcp_recovery", "recovery", None, None),
        _case("dns_failure", "protocol"),
        _case("gns3_process_unavailable", "lab"),
        _case("gns3_project_unavailable", "lab"),
        _case("hwsim_missing", "lab"),
        _case("hwsim_topology_mismatch", "lab"),
        _case("interface_carrier_failure", "network"),
        _case("disk_exhaustion", "runner"),
        _case("clock_ntp_failure", "runner"),
        _case("command_timeout", "runner", FailureClass.TIMED_OUT, RunLifecycle.ABORTED),
        _case("worker_crash", "runner", FailureClass.WORKER_CRASHED, RunLifecycle.ABORTED),
        _case("runner_disconnect", "runner", FailureClass.RUNNER_DISCONNECTED, RunLifecycle.ABORTED),
        _case("network_partition", "network", FailureClass.RUNNER_DISCONNECTED, RunLifecycle.ABORTED),
        _case("sync_endpoint_unavailable", "sync", None, None),
        _case("artifact_corruption", "evidence"),
        _case("database_interruption", "persistence"),
        _case("firmware_checksum_failure", "firmware", FailureClass.PRODUCT_FAILED, RunLifecycle.FAILED),
        _case("firmware_signature_failure", "firmware", FailureClass.PRODUCT_FAILED, RunLifecycle.FAILED),
        _case("firmware_incompatibility", "firmware", FailureClass.PRODUCT_FAILED, RunLifecycle.FAILED),
        _case("rollback_failure", "firmware", FailureClass.PRODUCT_FAILED, RunLifecycle.FAILED),
        _case("stale_lock", "concurrency"),
        _case("duplicate_job_request", "api", None, None, idempotent=True),
        _case("duplicate_synchronization_request", "sync", None, None, idempotent=True),
    )
}

class FailureInjectionCatalog:
    @staticmethod
    def all() -> tuple[FailureInjectionCase, ...]:
        return tuple(FAILURE_INJECTION_CASES[key] for key in sorted(FAILURE_INJECTION_CASES))
    @staticmethod
    def get(case_id: str) -> FailureInjectionCase:
        try:
            return FAILURE_INJECTION_CASES[case_id]
        except KeyError as exc:
            raise KeyError(f"unknown failure-injection case: {case_id}") from exc
    @staticmethod
    def coverage() -> dict[str, int]:
        result: dict[str, int] = {}
        for case in FailureInjectionCatalog.all():
            result[case.category] = result.get(case.category, 0) + 1
        return result

class FailureInjectionHarness:
    """Hardware-free orchestration seam; real adapters remain outside this boundary."""
    def execute(self, case_id: str, *, inject: Callable[[FailureInjectionCase], None], observe: Callable[[FailureInjectionCase], FailureInjectionObservation], cleanup: Callable[[FailureInjectionCase], None] | None = None) -> FailureInjectionObservation:
        case = FailureInjectionCatalog.get(case_id)
        try:
            inject(case)
            return observe(case)
        finally:
            if cleanup is not None and case.requires_cleanup:
                cleanup(case)
