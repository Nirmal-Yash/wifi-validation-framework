from datetime import datetime, timezone

import pytest

from lib.domain import ArtifactType, Attempt, EvidenceState, Run
from lib.repositories import (
    SQLiteArtifactRepository, SQLiteAttemptRepository, SQLiteDatabase,
    SQLiteEventRepository, SQLiteRunRepository,
)
from lib.services import ArtifactService


def make_run():
    return Run(
        run_id="run-1",
        display_id="RUN-20260924-120000-0001",
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Smoke",
        selected_tests=("wifi.dhcp",),
        test_definition_versions={"wifi.dhcp": "1.0"},
        resolved_config={},
        configuration_hash="a" * 64,
        repository_commit="commit-1",
        created_at=datetime.now(timezone.utc),
    )


def attempt_service(database, attempt_id="attempt-1", number=1):
    SQLiteAttemptRepository(database).save(Attempt(attempt_id, "run-1", number))
    return ArtifactService.from_sqlite(database)


def test_register_file_hashes_and_verifies(tmp_path):
    database = SQLiteDatabase(tmp_path / "results.db")
    database.initialize()
    SQLiteRunRepository(database).save(make_run())
    service = ArtifactService(
        SQLiteArtifactRepository(database),
        SQLiteRunRepository(database),
        SQLiteEventRepository(database),
        id_generator=iter(["artifact-1", "event-1"]).__next__,
        clock=lambda: datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
    )
    path = tmp_path / "dhcp.pcap"
    path.write_bytes(b"real-pcap-bytes")

    artifact = service.register_file(
        run_id="run-1",
        path=path,
        artifact_type=ArtifactType.PCAP,
        expected_size_bytes=len(b"real-pcap-bytes"),
    )

    assert len(artifact.sha256) == 64
    assert artifact.display_name == "dhcp.pcap"
    assert artifact.size_bytes == len(b"real-pcap-bytes")
    assert artifact.created_at is not None
    assert service.verify(artifact.artifact_id)

    path.write_bytes(b"tampered")
    assert not service.verify(artifact.artifact_id)



def test_test_evidence_is_scoped_to_its_node_and_run_level_evidence_is_shared(tmp_path):
    database = SQLiteDatabase(tmp_path / "evidence.db")
    database.initialize()
    SQLiteRunRepository(database).save(make_run())
    service = attempt_service(database)
    SQLiteAttemptRepository(database).save(Attempt("attempt-2", "run-1", 2))
    pcap_a = tmp_path / "a.pcap"
    pcap_b = tmp_path / "b.pcap"
    run_log = tmp_path / "run.log"
    pcap_a.write_bytes(b"capture-a")
    pcap_b.write_bytes(b"capture-b")
    run_log.write_bytes(b"run-wide-log")
    service.register_file(
        run_id="run-1", path=pcap_a, artifact_type=ArtifactType.PCAP,
        test_node_id="tests/test_a.py::test_a", attempt_id="attempt-1",
    )
    service.register_file(
        run_id="run-1", path=pcap_b, artifact_type=ArtifactType.PCAP,
        test_node_id="tests/test_b.py::test_b", attempt_id="attempt-1",
    )

    assert service.evaluate_test_evidence(
        run_id="run-1", node_id="tests/test_a.py::test_a", required_types=(ArtifactType.PCAP,), attempt_id="attempt-1"
    ).value == "COMPLETE"
    assert service.evaluate_test_evidence(
        run_id="run-1", node_id="tests/test_c.py::test_c", required_types=(ArtifactType.PCAP,), attempt_id="attempt-1"
    ).value == "INCOMPLETE"
    assert service.evaluate_test_evidence(
        run_id="run-1", node_id="tests/test_a.py::test_a",
        required_types=(ArtifactType.PCAP,), attempt_id="attempt-2",
    ).value == "INCOMPLETE"

    service.register_file(run_id="run-1", path=run_log, artifact_type=ArtifactType.SETUP_LOG)
    assert service.evaluate_test_evidence(
        run_id="run-1", node_id="tests/test_c.py::test_c", required_types=(ArtifactType.SETUP_LOG,), attempt_id="attempt-2"
    ).value == "COMPLETE"

    attempt_log = tmp_path / "attempt.log"
    attempt_log.write_bytes(b"attempt-one-log")
    service.register_file(
        run_id="run-1", path=attempt_log, artifact_type=ArtifactType.COMMAND_OUTPUT,
        attempt_id="attempt-1",
    )
    assert service.evaluate_test_evidence(
        run_id="run-1", node_id="tests/test_c.py::test_c",
        required_types=(ArtifactType.COMMAND_OUTPUT,), attempt_id="attempt-1",
    ).value == "COMPLETE"
    assert service.evaluate_test_evidence(
        run_id="run-1", node_id="tests/test_c.py::test_c",
        required_types=(ArtifactType.COMMAND_OUTPUT,), attempt_id="attempt-2",
    ).value == "INCOMPLETE"


def test_test_evidence_detects_corrupted_node_owned_artifact(tmp_path):
    database = SQLiteDatabase(tmp_path / "invalid-evidence.db")
    database.initialize()
    SQLiteRunRepository(database).save(make_run())
    service = attempt_service(database)
    capture = tmp_path / "capture.pcap"
    capture.write_bytes(b"authentic-pcap")
    service.register_file(
        run_id="run-1", path=capture, artifact_type=ArtifactType.PCAP,
        test_node_id="tests/test_a.py::test_a", attempt_id="attempt-1",
    )
    capture.write_bytes(b"tampered")

    assert service.evaluate_test_evidence(
        run_id="run-1", node_id="tests/test_a.py::test_a", required_types=(ArtifactType.PCAP,), attempt_id="attempt-1"
    ).value == "INVALID"


def test_soft_deleted_artifact_cannot_satisfy_required_evidence(tmp_path):
    database = SQLiteDatabase(tmp_path / "soft-deleted-evidence.db")
    database.initialize()
    SQLiteRunRepository(database).save(make_run())
    service = attempt_service(database)
    capture = tmp_path / "capture.pcap"
    capture.write_bytes(b"authentic-pcap")
    artifact = service.register_file(
        run_id="run-1", path=capture, artifact_type=ArtifactType.PCAP,
        test_node_id="tests/test_a.py::test_a", attempt_id="attempt-1",
    )
    with database.connection() as connection:
        connection.execute(
            "UPDATE artifacts SET soft_deleted_at = ? WHERE artifact_id = ?",
            ("2026-11-03T12:00:00+00:00", artifact.artifact_id),
        )
        connection.commit()

    assert service.evaluate_test_evidence(
        run_id="run-1", node_id="tests/test_a.py::test_a", required_types=(ArtifactType.PCAP,), attempt_id="attempt-1"
    ).value == "INCOMPLETE"


def test_result_linked_artifact_satisfies_only_its_own_test(tmp_path):
    from lib.domain import Attempt, Criticality, Severity, TestResult, TestResultStatus
    from lib.repositories import SQLiteAttemptRepository, SQLiteTestResultRepository

    database = SQLiteDatabase(tmp_path / "result-owned-evidence.db")
    database.initialize()
    SQLiteRunRepository(database).save(make_run())
    SQLiteAttemptRepository(database).save(Attempt("attempt-1", "run-1", 1))
    SQLiteTestResultRepository(database).save(
        TestResult(
            test_result_id="test-result-1",
            run_id="run-1",
            attempt_id="attempt-1",
            test_id="wifi.dhcp",
            node_id="tests/test_dhcp.py::test_dhcp_lease_assigned",
            test_version="1.0",
            status=TestResultStatus.PASS,
            criticality=Criticality.BLOCKING,
            severity=Severity.HIGH,
            evidence_state=EvidenceState.NOT_REQUIRED,
        )
    )
    service = ArtifactService.from_sqlite(database)
    capture = tmp_path / "dhcp.pcap"
    capture.write_bytes(b"result-owned-capture")
    service.register_file(
        run_id="run-1", path=capture, artifact_type=ArtifactType.PCAP,
        test_result_id="test-result-1",
    )

    assert service.evaluate_test_evidence(
        run_id="run-1",
        node_id="tests/test_dhcp.py::test_dhcp_lease_assigned",
        required_types=(ArtifactType.PCAP,),
        attempt_id="attempt-1",
    ).value == "COMPLETE"
    assert service.evaluate_test_evidence(
        run_id="run-1",
        node_id="tests/test_dns.py::test_dns_resolution",
        required_types=(ArtifactType.PCAP,),
        attempt_id="attempt-1",
    ).value == "INCOMPLETE"


def test_artifact_registration_rejects_test_result_from_another_run(tmp_path):
    from lib.domain import Attempt, Criticality, Severity, TestResult, TestResultStatus
    from lib.repositories import SQLiteAttemptRepository, SQLiteTestResultRepository

    database = SQLiteDatabase(tmp_path / "cross-run-evidence.db")
    database.initialize()
    SQLiteRunRepository(database).save(make_run())
    other_run = make_run()
    other_run.run_id = "run-2"
    other_run.display_id = "RUN-20261103-120000-0002"
    SQLiteRunRepository(database).save(other_run)
    SQLiteAttemptRepository(database).save(Attempt("attempt-2", "run-2", 1))
    SQLiteTestResultRepository(database).save(
        TestResult(
            test_result_id="result-run-2", run_id="run-2", attempt_id="attempt-2",
            test_id="wifi.dhcp", node_id="tests/test_dhcp.py::test_dhcp_lease_assigned",
            test_version="1.0", status=TestResultStatus.PASS,
            criticality=Criticality.BLOCKING, severity=Severity.HIGH,
            evidence_state=EvidenceState.NOT_REQUIRED,
        )
    )
    service = ArtifactService.from_sqlite(database)
    capture = tmp_path / "cross-run.pcap"
    capture.write_bytes(b"capture")

    with pytest.raises(ValueError, match="same Run"):
        service.register_file(
            run_id="run-1", path=capture, artifact_type=ArtifactType.PCAP,
            test_result_id="result-run-2",
        )
