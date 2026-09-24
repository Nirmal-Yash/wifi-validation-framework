from datetime import datetime, timezone

from lib.domain import ArtifactType, Run
from lib.repositories import SQLiteArtifactRepository, SQLiteDatabase, SQLiteEventRepository, SQLiteRunRepository
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

