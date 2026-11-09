from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping
from lib.domain import ReleaseWaiver, WaiverScope

class ReleaseGateStatus(str, Enum):
    ACCEPT = 'ACCEPT'
    REJECT = 'REJECT'

@dataclass(frozen=True, slots=True)
class ReleaseGatePolicy:
    disallowed_classifications: frozenset[str] = frozenset({'REGRESSION','SOFT_REGRESSION','NEW_FAILURE','NO_BASELINE','UNVALIDATED'})
    require_healthy_lab: bool = True
    require_completed_run: bool = True
    require_all_required_tests: bool = True
    require_valid_required_evidence: bool = True

@dataclass(frozen=True, slots=True)
class ReleaseGateIssue:
    code: str
    message: str
    test_id: str | None = None

@dataclass(frozen=True, slots=True)
class ReleaseGateInput:
    run_lifecycle: str
    lab_health: str | None
    baseline_available: bool
    required_test_ids: tuple[str, ...]
    observed_test_ids: tuple[str, ...]
    test_statuses: Mapping[str, str]
    evidence_states: Mapping[str, str]
    regression_classifications: Mapping[str, str]
    policy: ReleaseGatePolicy = field(default_factory=ReleaseGatePolicy)
    waivers: tuple[ReleaseWaiver, ...] = ()
    run_id: str | None = None

@dataclass(frozen=True, slots=True)
class ReleaseGateWaivedIssue:
    issue: ReleaseGateIssue
    waiver_id: str
    audit_reference: str


@dataclass(frozen=True, slots=True)
class ReleaseGateDecision:
    status: ReleaseGateStatus
    issues: tuple[ReleaseGateIssue, ...] = ()
    summary: str = ''
    waived_issues: tuple[ReleaseGateWaivedIssue, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.status is ReleaseGateStatus.ACCEPT

class ReleaseGateEvaluator:
    def evaluate(self, data: ReleaseGateInput) -> ReleaseGateDecision:
        issues: list[ReleaseGateIssue] = []
        if data.policy.require_completed_run and data.run_lifecycle != 'COMPLETED':
            issues.append(ReleaseGateIssue('RUN_NOT_COMPLETED', f'current Run lifecycle is {data.run_lifecycle}'))
        if data.policy.require_healthy_lab and data.lab_health != 'HEALTHY':
            issues.append(ReleaseGateIssue('LAB_NOT_HEALTHY', f'lab health is {data.lab_health or "UNKNOWN"}'))
        if not data.baseline_available:
            issues.append(ReleaseGateIssue('NO_BASELINE', 'no comparable baseline is available'))
        required = set(data.required_test_ids)
        observed = set(data.observed_test_ids)
        if data.policy.require_all_required_tests:
            for test_id in sorted(required - observed):
                issues.append(ReleaseGateIssue("MISSING_REQUIRED_TEST", "required test has no persisted current result", test_id))
        for test_id in sorted(required):
            if test_id not in data.regression_classifications:
                issues.append(ReleaseGateIssue("MISSING_REGRESSION_CLASSIFICATION", "required test has no regression classification against the selected baseline", test_id))
        for test_id, classification in sorted(data.regression_classifications.items()):
            if classification in data.policy.disallowed_classifications:
                issues.append(ReleaseGateIssue("DISALLOWED_REGRESSION_CLASS", f"regression classification {classification} is not releasable", test_id))
        for test_id in sorted(required):
            status = data.test_statuses.get(test_id, "MISSING")
            if status != "PASS":
                issues.append(ReleaseGateIssue("NON_PASSING_TEST", f"current required test status is {status}", test_id))
        if data.policy.require_valid_required_evidence:
            for test_id in sorted(required):
                state = data.evidence_states.get(test_id, "MISSING")
                if state not in {"COMPLETE", "NOT_REQUIRED"}:
                    issues.append(ReleaseGateIssue("INVALID_REQUIRED_EVIDENCE", f"required evidence state is {state}", test_id))
        active_waivers = [w for w in data.waivers if w.is_active()]

        def waiver_matches_issue(waiver: ReleaseWaiver, issue: ReleaseGateIssue) -> bool:
            if waiver.issue_code != issue.code:
                return False
            target = waiver.target_id
            if waiver.scope is WaiverScope.TEST:
                return issue.test_id is not None and target == issue.test_id
            if waiver.scope is WaiverScope.RUN:
                return data.run_id is not None and target == data.run_id
            if waiver.scope is WaiverScope.REGRESSION:
                return issue.test_id is not None and target == issue.test_id and issue.code == "DISALLOWED_REGRESSION_CLASS"
            if waiver.scope is WaiverScope.RELEASE:
                return target == "*" or (data.run_id is not None and target == data.run_id)
            return False

        remaining: list[ReleaseGateIssue] = []
        waived: list[ReleaseGateWaivedIssue] = []
        for issue in issues:
            waiver = next((candidate for candidate in active_waivers if waiver_matches_issue(candidate, issue)), None)
            if waiver is None:
                remaining.append(issue)
            else:
                waived.append(ReleaseGateWaivedIssue(issue, waiver.waiver_id, waiver.audit_reference))
        status = ReleaseGateStatus.REJECT if remaining else ReleaseGateStatus.ACCEPT
        summary = "release gate accepted" if status is ReleaseGateStatus.ACCEPT else f"release gate rejected with {len(remaining)} issue(s)"
        return ReleaseGateDecision(status, tuple(remaining), summary, tuple(waived))