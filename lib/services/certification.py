from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import subprocess
from pathlib import Path
import re
from typing import Mapping


@dataclass(frozen=True, slots=True)
class CertificationScenario:
    scenario_id: str
    name: str
    expected_lifecycle: str
    expected_outcome: str | None
    required_controls: tuple[str, ...]
    execution_class: str
    objective: str = ""
    preconditions: tuple[str, ...] = ()
    execution_method: str = ""
    expected_behavior: str = ""
    required_evidence_types: tuple[str, ...] = ()
    verification_criteria: tuple[str, ...] = ()


CERTIFICATION_SCENARIOS: tuple[CertificationScenario, ...] = (
    CertificationScenario(
        "healthy_run", "Healthy Run", "COMPLETED", "VALIDATED",
        ("required_tests", "required_evidence", "telemetry", "regression", "lineage"),
        "HARDWARE_FREE_PLUS_REAL_LAB",
        "Prove a healthy validation Run completes with authoritative results and comparable evidence.",
        ("Runner dependencies are installed.", "Database is at the current Alembic head.", "A compatible baseline exists.", "The protected lab is healthy for the REAL_LAB execution."),
        "Execute the selected registered profile once in hardware-free integration and once on the protected lab.",
        "The Run completes, required tests pass, evidence verifies, telemetry is classified, and the baseline comparison is reproducible.",
        ("RUN_SNAPSHOT", "TEST_RESULTS_JSON", "METRICS_JSON", "PCAP", "PROTOCOL_JSON", "TELEMETRY_JSON", "LAB_HEALTH_SNAPSHOT", "ENVIRONMENT_FINGERPRINT"),
        ("Latest Attempt is authoritative.", "Every required test has exactly one persisted result.", "All evidence hashes verify.", "The real-lab execution identifies the tested source commit and environment."),
    ),
    CertificationScenario(
        "product_failure", "Real product failure", "FAILED", "REJECTED",
        ("failure_evidence", "product_statistics", "complete_lifecycle"),
        "SIMULATED_PLUS_REAL_LAB",
        "Prove a genuine validation/product failure is classified separately from Runner or lab failure.",
        ("A controlled, reversible product-failure scenario is approved.", "Management access and cleanup are available."),
        "Exercise a deterministic simulated fault and an approved real-lab product-failure case.",
        "The Run is rejected as a product failure, raw observations are preserved, and cleanup completes.",
        ("RUN_SNAPSHOT", "TEST_RESULTS_JSON", "DIAGNOSTIC_BUNDLE", "COMMAND_AUDIT_JSON"),
        ("Failure class is PRODUCT_FAILURE.", "The failed test and relevant metrics remain persisted.", "Restoration and finalization are verified."),
    ),
    CertificationScenario(
        "missing_evidence", "Missing evidence", "COMPLETED", "UNVALIDATED",
        ("evidence_integrity", "pass_blocked"),
        "HARDWARE_FREE",
        "Prove a nominal test result cannot be promoted when required evidence is missing or invalid.",
        ("A hardware-free test fixture and required-evidence declaration are available."),
        "Run the evidence contract test with a required artifact deliberately omitted or corrupted.",
        "The test may complete, but its outcome is UNVALIDATED and the release gate rejects it.",
        ("RUN_SNAPSHOT", "RELEASE_GATE_DECISION_JSON", "EVIDENCE_VALIDATION_REPORT"),
        ("Missing/corrupt evidence is explicitly classified.", "No PASS/baseline promotion is granted.", "The rejection identifies the missing requirement."),
    ),
    CertificationScenario(
        "lab_failure", "Lab failure", "LAB_FAILED", "UNVALIDATED",
        ("infra_classification", "statistics_isolation", "cleanup"),
        "HARDWARE_FREE_PLUS_REAL_LAB",
        "Prove unavailable or unhealthy lab infrastructure is not misreported as a product failure.",
        ("A hardware-free failure fixture is available.", "The protected-lab case uses an approved recoverable disruption."),
        "Inject a bounded health failure in simulation, then exercise the approved protected-lab failure path.",
        "The Run is LAB_FAILED/UNVALIDATED, product statistics are not contaminated, and recovery is recorded.",
        ("RUN_SNAPSHOT", "LAB_HEALTH_SNAPSHOT", "DIAGNOSTIC_BUNDLE", "RECOVERY_REPORT"),
        ("Failure class is LAB_FAILURE.", "No product PASS/FAIL is inferred from infrastructure loss.", "Cleanup and post-failure health are evidenced."),
    ),
    CertificationScenario(
        "runner_failure", "Runner/worker failure", "ABORTED", "UNVALIDATED",
        ("failure_class", "diagnostics", "cleanup"),
        "HARDWARE_FREE",
        "Prove a worker/Runner crash is recovered and does not become a product result.",
        ("A disposable hardware-free Runner database and worker fixture are available."),
        "Terminate a controlled worker after Run start and execute restart recovery.",
        "The Run is ABORTED/UNVALIDATED with WORKER_CRASHED classification and diagnostic evidence.",
        ("RUN_SNAPSHOT", "DIAGNOSTIC_BUNDLE", "PROCESS_LOG", "RECOVERY_REPORT"),
        ("Dead worker ownership is detected safely.", "Run finalization is persisted once.", "Leases and child processes are cleaned up."),
    ),
    CertificationScenario(
        "timeout_cancellation", "Timeout and cancellation", "ABORTED_OR_CANCELLED", "UNVALIDATED",
        ("child_cleanup", "unlock", "evidence_preservation"),
        "HARDWARE_FREE",
        "Prove timeout and operator cancellation terminate owned processes and release resources.",
        ("A disposable process fixture and isolated lock directory are available."),
        "Exercise timeout, SIGTERM grace, SIGKILL escalation and an explicit cancellation request.",
        "The Run reaches the defined terminal state, child processes stop, locks release, and prior evidence remains intact.",
        ("RUN_SNAPSHOT", "PROCESS_LOG", "RESOURCE_LEASE_JSON", "CANCELLATION_AUDIT_JSON"),
        ("Only owned processes are terminated.", "PID reuse cannot terminate unrelated processes.", "Finalization and lease release occur on all paths."),
    ),
    CertificationScenario(
        "concurrent_execution", "Concurrent execution", "QUEUED_OR_COMPLETED", None,
        ("exclusive_lock", "no_destructive_race", "consistent_state"),
        "HARDWARE_FREE_PLUS_REAL_LAB",
        "Prove exclusive physical-resource ownership prevents conflicting concurrent Runs.",
        ("Two isolated workers and a shared resource identity are available.", "The real-lab case is explicitly scheduled and authorized."),
        "Launch overlapping acquisitions for the same resource and then run the guarded real-lab concurrency check.",
        "At most one owner holds the exclusive lease; the contender waits or fails cleanly without mutation.",
        ("RUN_SNAPSHOT", "RESOURCE_LEASE_JSON", "LOCK_AUDIT_JSON", "CONCURRENCY_REPORT"),
        ("Lock inode identity remains stable.", "Lease acquisition/release is atomic.", "No overlapping mutation or inconsistent persisted state occurs."),
    ),
    CertificationScenario(
        "firmware_lifecycle", "Firmware lifecycle", "COMPLETED_OR_FAILED", None,
        ("integrity", "authorization", "state_transitions", "audit"),
        "FAKE_ADAPTER_PLUS_PROTECTED_TARGET",
        "Prove firmware validation and lifecycle safeguards, followed by target-specific physical acceptance.",
        ("A fake adapter is available.", "A real target, approved firmware image, maintenance window and rollback plan are available for PROTECTED_TARGET."),
        "Exercise the lifecycle with fake adapters, then perform an operator-approved physical flash/reboot/version check/rollback.",
        "Image provenance and compatibility are checked; each mutation is authorized and audited; rollback verifies the expected version.",
        ("FIRMWARE_IMAGE_MANIFEST", "FIRMWARE_OPERATION_AUDIT", "DEVICE_VERSION_JSON", "ROLLBACK_VERIFICATION"),
        ("No unverified image is flashed.", "No silent retry or implicit rollback occurs.", "Physical target returns the independently verified expected firmware version."),
    ),
    CertificationScenario(
        "offline_operation", "Offline operation", "COMPLETED_OR_TERMINAL", None,
        ("local_authority", "queue", "idempotency", "retry"),
        "HARDWARE_FREE",
        "Prove local Runs remain authoritative while synchronization is unavailable and recoverable.",
        ("A disposable SQLite database and a deterministic sync transport stub are available."),
        "Complete a Run with synchronization unavailable; restore transport and retry the queued snapshot.",
        "Local Run/TestResult facts remain unchanged, delivery is retried idempotently, and duplicate delivery is safe.",
        ("RUN_SNAPSHOT", "SYNC_QUEUE_SNAPSHOT", "IDEMPOTENCY_AUDIT_JSON", "SYNC_RETRY_REPORT"),
        ("Queue claim/lease is durable.", "Stale claims recover.", "Sync failure does not change Run outcome.", "Retry reuses the idempotency key."),
    ),
    CertificationScenario(
        "restart_recovery", "Restart recovery", "RECOVERED", None,
        ("run_recovery", "lock_recovery", "sync_recovery"),
        "HARDWARE_FREE",
        "Prove interrupted Runs, resource leases and sync claims recover safely after restart.",
        ("A disposable database, lock directory and queued sync item are available."),
        "Restart after Run start, resource lock acquisition and sync claim, then invoke recovery services.",
        "Abandoned owned state is recovered without duplicating destructive work or deleting active lock inodes.",
        ("RUN_RECOVERY_REPORT", "RESOURCE_LEASE_JSON", "SYNC_QUEUE_SNAPSHOT", "RECOVERY_AUDIT_JSON"),
        ("Live processes/leases are not reclaimed.", "Dead workers are finalized once.", "Lock inode identity is preserved.", "Sync lease is retryable."),
    ),
    CertificationScenario(
        "real_lab_baseline", "Protected 11-test real-lab baseline", "COMPLETED", "VALIDATED",
        ("pcap", "protocol_evidence", "telemetry", "metrics", "hashes", "lab_health", "fingerprint"),
        "REAL_LAB",
        "Re-establish the protected 11-test GNS3/mac80211_hwsim baseline with genuine packet and runtime evidence.",
        ("The protected GNS3/mac80211_hwsim lab is reachable.", "Approved topology, 12-hour lease and capture paths remain unchanged.", "Any DHCP T1/T2 short-lease window has separate operator approval."),
        "Run the canonical protected real-lab suite and approved live protocol/performance capture workflows.",
        "The protected suite completes with valid persisted results and actual PCAP, protocol, telemetry, health and fingerprint evidence.",
        ("TEST_RESULTS_JSON", "PCAP", "PROTOCOL_JSON", "TELEMETRY_JSON", "METRICS_JSON", "LAB_HEALTH_SNAPSHOT", "ENVIRONMENT_FINGERPRINT", "ARTIFACT_HASH_MANIFEST"),
        ("The test source commit matches the certified checkout.", "Capture files are from the protected lab.", "Remote/local PCAP SHA-256 matches.", "Virtual Wi-Fi is not represented as physical RF.", "No synthetic artifact satisfies the REAL_LAB execution class."),
    ),
)


_EXECUTION_CLASSES = {
    "HARDWARE_FREE_PLUS_REAL_LAB": ("HARDWARE_FREE", "REAL_LAB"),
    "SIMULATED_PLUS_REAL_LAB": ("SIMULATED", "REAL_LAB"),
    "FAKE_ADAPTER_PLUS_PROTECTED_TARGET": ("FAKE_ADAPTER", "PROTECTED_TARGET"),
    "HARDWARE_FREE": ("HARDWARE_FREE",),
    "REAL_LAB": ("REAL_LAB",),
}


@dataclass(frozen=True, slots=True)
class CertificationEvaluation:
    complete: bool
    missing_scenarios: tuple[str, ...]
    issues: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_complete": self.complete,
            "missing_scenarios": list(self.missing_scenarios),
            "issues": list(self.issues),
        }


class CertificationMatrix:
    def __init__(self, scenarios: tuple[CertificationScenario, ...] = CERTIFICATION_SCENARIOS):
        ids = [item.scenario_id for item in scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate certification scenario id")
        self.scenarios = scenarios
        self._by_id = {item.scenario_id: item for item in scenarios}

    def get(self, scenario_id: str) -> CertificationScenario:
        return self._by_id[scenario_id]

    @staticmethod
    def required_execution_classes(scenario: CertificationScenario) -> tuple[str, ...]:
        return _EXECUTION_CLASSES[scenario.execution_class]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "netregress-certification.v2",
            "scenario_count": len(self.scenarios),
            "scenarios": [
                {
                    "scenario_id": scenario.scenario_id,
                    "name": scenario.name,
                    "objective": scenario.objective,
                    "preconditions": list(scenario.preconditions),
                    "execution_method": scenario.execution_method,
                    "expected_lifecycle": scenario.expected_lifecycle,
                    "expected_outcome": scenario.expected_outcome,
                    "expected_behavior": scenario.expected_behavior,
                    "required_controls": list(scenario.required_controls),
                    "required_evidence_types": list(scenario.required_evidence_types),
                    "verification_criteria": list(scenario.verification_criteria),
                    "execution_class": scenario.execution_class,
                    "required_execution_classes": list(self.required_execution_classes(scenario)),
                }
                for scenario in self.scenarios
            ],
        }

    def validate_evidence(self, evidence: Mapping[str, Mapping[str, object]]) -> tuple[str, ...]:
        """Legacy structural validator retained for compatibility only.

        This checks declared control names. It is not certification evidence
        and must not be used to claim that a scenario has passed.
        """
        missing = []
        for scenario in self.scenarios:
            record = evidence.get(scenario.scenario_id)
            if record is None:
                missing.append(scenario.scenario_id)
                continue
            observed = set(record.get("controls", ()))
            if any(control not in observed for control in scenario.required_controls):
                missing.append(scenario.scenario_id)
        return tuple(sorted(missing))

    @staticmethod
    def _verify_artifact(item: Mapping[str, object], root: Path) -> tuple[str | None, str | None]:
        relative = item.get("path")
        expected_hash = item.get("sha256")
        evidence_type = item.get("type")
        if not isinstance(evidence_type, str) or not evidence_type.strip():
            return None, "artifact type is missing"
        if not isinstance(relative, str) or not relative.strip():
            return None, "artifact path is missing"
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
            return None, "artifact SHA-256 is missing or malformed"
        candidate = Path(relative).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        results_path = root / "results"
        if results_path.is_symlink():
            return None, "results directory must not be a symlink"
        allowed_root = results_path.resolve()
        if not allowed_root.is_relative_to(root.resolve()):
            return None, "results directory resolves outside the repository"
        if not resolved.is_relative_to(allowed_root):
            return None, "artifact path is outside the results directory"
        if not resolved.is_file():
            return None, f"artifact is unavailable: {relative}"
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != expected_hash.lower():
            return None, f"artifact SHA-256 mismatch: {relative}"
        return evidence_type.upper(), None

    @staticmethod
    def _current_commit(root: Path) -> str | None:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return None
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if status.returncode != 0 or status.stdout.strip():
            return None
        commit = result.stdout.strip()
        return commit or None

    def evaluate_evidence(
        self,
        evidence: Mapping[str, Mapping[str, object]],
        *,
        root: str | Path,
    ) -> CertificationEvaluation:
        """Validate scenario outcomes, exact execution classes and bound evidence.

        The evidence JSON is an operator/Runner attestation, not a cryptographic
        signature. Each execution is bound to the checked-out source commit,
        a 64-character environment fingerprint, a command, timezone-aware
        timestamp and SHA-256-verified files stored beneath results/.
        REAL_LAB and PROTECTED_TARGET records additionally require an operator
        identity and explicit approval reference.
        """
        repository_root = Path(root).expanduser().resolve()
        source_commit = self._current_commit(repository_root)
        missing: list[str] = []
        issues: list[str] = []

        used_execution_ids: set[str] = set()
        for scenario in self.scenarios:
            record = evidence.get(scenario.scenario_id)
            scenario_issues: list[str] = []
            observed_types: set[str] = set()

            if not isinstance(record, Mapping):
                scenario_issues.append("scenario record is missing")
            else:
                if str(record.get("status", "")).upper() != "PASS":
                    scenario_issues.append("scenario status must be PASS")
                observed_lifecycle = str(record.get("lifecycle", "")).upper()
                expected_lifecycles = {value.strip() for value in scenario.expected_lifecycle.split("_OR_")}
                if observed_lifecycle not in expected_lifecycles:
                    scenario_issues.append(f"lifecycle {observed_lifecycle or 'MISSING'} does not match {scenario.expected_lifecycle}")
                if scenario.expected_outcome is not None:
                    observed_outcome = str(record.get("outcome", "")).upper()
                    if observed_outcome != scenario.expected_outcome:
                        scenario_issues.append(f"outcome {observed_outcome or 'MISSING'} does not match {scenario.expected_outcome}")

                controls = record.get("controls", ())
                observed_controls = set(controls) if isinstance(controls, (list, tuple, set)) else set()
                missing_controls = sorted(set(scenario.required_controls) - observed_controls)
                if missing_controls:
                    scenario_issues.append("missing controls: " + ", ".join(missing_controls))

                executions = record.get("executions", ())
                if not isinstance(executions, list):
                    executions = []
                for required_class in self.required_execution_classes(scenario):
                    matched = [
                        item for item in executions
                        if isinstance(item, Mapping)
                        and str(item.get("execution_class", "")).upper() == required_class
                    ]
                    valid_class_execution = False
                    for execution in matched:
                        execution_id = execution.get("execution_id")
                        if not isinstance(execution_id, str) or not execution_id.strip() or execution_id in used_execution_ids:
                            continue
                        if source_commit is None or execution.get("source_commit") != source_commit:
                            continue
                        fingerprint = execution.get("environment_fingerprint")
                        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint):
                            continue
                        if not isinstance(execution.get("command"), str) or not execution.get("command", "").strip():
                            continue
                        if str(execution.get("status", "")).upper() != "PASS":
                            continue
                        try:
                            timestamp = datetime.fromisoformat(str(execution.get("executed_at", "")).replace("Z", "+00:00"))
                            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                                continue
                        except (TypeError, ValueError):
                            continue
                        if required_class in {"REAL_LAB", "PROTECTED_TARGET"}:
                            if not str(execution.get("operator", "")).strip():
                                continue
                            if not str(execution.get("approval_reference", "")).strip():
                                continue

                        artifacts = execution.get("evidence", ())
                        if not isinstance(artifacts, list) or not artifacts:
                            continue
                        artifact_types: set[str] = set()
                        artifact_errors: list[str] = []
                        for artifact in artifacts:
                            if not isinstance(artifact, Mapping):
                                artifact_errors.append("evidence entry must be an object")
                                continue
                            evidence_type, error = self._verify_artifact(artifact, repository_root)
                            if error:
                                artifact_errors.append(error)
                            elif evidence_type:
                                artifact_types.add(evidence_type)
                        if artifact_errors:
                            continue

                        used_execution_ids.add(execution_id)
                        observed_types.update(artifact_types)
                        valid_class_execution = True
                        break
                    if not valid_class_execution:
                        scenario_issues.append(
                            f"no verified PASS execution/evidence for execution class {required_class}"
                        )

                missing_types = sorted(set(scenario.required_evidence_types) - observed_types)
                if missing_types:
                    scenario_issues.append("missing evidence types: " + ", ".join(missing_types))

            if scenario_issues:
                missing.append(scenario.scenario_id)
                issues.extend(f"{scenario.scenario_id}: {message}" for message in scenario_issues)

        return CertificationEvaluation(
            complete=not missing,
            missing_scenarios=tuple(sorted(missing)),
            issues=tuple(sorted(issues)),
        )
