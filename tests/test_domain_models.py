from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lib.domain import (
    Artifact,
    ArtifactType,
    Attempt,
    Criticality,
    DomainValidationError,
    EvidenceState,
    Metric,
    Run,
    Sample,
    Severity,
    TestResult as DomainTestResult,
    TestResultStatus as DomainTestResultStatus,
)

NOW = datetime.now(timezone.utc)


def make_run() -> Run:
    selected = ("wifi.latency.threshold", "wifi.dhcp.lease")
    return Run(
        run_id="01JRUNEXAMPLE00000000000000",
        display_id="RUN-20260924-121700-0001",
        firmware_version="v1.0",
        lab_id="lab-01",
        validation_profile="Standard Regression",
        selected_tests=selected,
        test_definition_versions={test_id: "1.0" for test_id in selected},
        resolved_config={"network": {"client_interface": "wlan0"}},
        configuration_hash="a" * 64,
        repository_commit="ed798a6f13b745420adbe235b2ca465425720896",
    )


def test_run_requires_definition_version_for_every_selected_test() -> None:
    with pytest.raises(DomainValidationError):
        Run(
            run_id="run-1",
            display_id="RUN-20260924-121700-0001",
            firmware_version="v1.0",
            lab_id="lab-01",
            validation_profile="Smoke",
            selected_tests=("wifi.auth",),
            test_definition_versions={},
            resolved_config={},
            configuration_hash="a" * 64,
            repository_commit="abc123",
        )


def test_attempt_rejects_result_from_another_run() -> None:
    attempt = Attempt("attempt-1", "run-1", 1)
    result = DomainTestResult(
        test_result_id="result-1",
        run_id="run-2",
        attempt_id="attempt-1",
        test_id="wifi.auth",
        node_id="tests/test_auth.py::test_wpa2_authentication",
        test_version="1.0",
        status=DomainTestResultStatus.FAIL,
        criticality=Criticality.BLOCKING,
        severity=Severity.HIGH,
        evidence_state=EvidenceState.COMPLETE,
    )
    with pytest.raises(DomainValidationError):
        attempt.add_result(result)


def test_pass_cannot_have_invalid_evidence() -> None:
    with pytest.raises(DomainValidationError):
        DomainTestResult(
            test_result_id="result-1",
            run_id="run-1",
            attempt_id="attempt-1",
            test_id="wifi.dhcp",
            node_id="tests/test_dhcp.py::test_dhcp_lease_assigned",
            test_version="1.0",
            status=DomainTestResultStatus.PASS,
            criticality=Criticality.BLOCKING,
            severity=Severity.HIGH,
            evidence_state=EvidenceState.INVALID,
        )


def test_unvalidated_requires_non_complete_evidence_state() -> None:
    with pytest.raises(DomainValidationError):
        DomainTestResult(
            test_result_id="result-1",
            run_id="run-1",
            attempt_id="attempt-1",
            test_id="wifi.capture",
            node_id="tests/test_packet_capture.py::test_pcap_contains_dhcp_packets",
            test_version="1.0",
            status=DomainTestResultStatus.UNVALIDATED,
            criticality=Criticality.BLOCKING,
            severity=Severity.HIGH,
            evidence_state=EvidenceState.COMPLETE,
        )


def test_authoritative_metric_requires_sample() -> None:
    with pytest.raises(DomainValidationError):
        Metric(name="latency", unit="ms", authoritative=True)


def test_attempt_numbers_are_sequential() -> None:
    run = make_run()
    run.add_attempt(Attempt("attempt-1", run.run_id, 1))
    with pytest.raises(DomainValidationError):
        run.add_attempt(Attempt("attempt-3", run.run_id, 3))


def test_artifact_sha256_and_size_are_validated() -> None:
    artifact = Artifact(
        artifact_id="artifact-1",
        run_id="run-1",
        artifact_type=ArtifactType.PCAP,
        path="results/captures/dhcp_test.pcap",
        sha256="b" * 64,
        size_bytes=128,
    )
    assert artifact.size_bytes == 128


def test_sample_preserves_warmup_and_retry_metadata() -> None:
    sample = Sample(value=12.5, warmup=True, retried=True, captured_at=NOW)
    assert sample.warmup is True
    assert sample.retried is True
