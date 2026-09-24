from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from lib.domain import Artifact, ArtifactType, EvidenceState, LifecycleEvent
from lib.repositories import (
    ArtifactRepository,
    EventRepository,
    RunRepository,
    SQLiteArtifactRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
)
from .run_service import generate_ulid


class ArtifactService:
    """Verify, hash, and register immutable Run-scoped evidence files."""

    def __init__(
        self,
        artifact_repository: ArtifactRepository,
        run_repository: RunRepository,
        event_repository: EventRepository,
        *,
        id_generator=generate_ulid,
        clock=lambda: datetime.now(timezone.utc),
    ):
        self.artifact_repository = artifact_repository
        self.run_repository = run_repository
        self.event_repository = event_repository
        self.id_generator = id_generator
        self.clock = clock

    @classmethod
    def from_sqlite(cls, database: SQLiteDatabase, **kwargs):
        database.initialize()
        return cls(
            SQLiteArtifactRepository(database),
            SQLiteRunRepository(database),
            SQLiteEventRepository(database),
            **kwargs,
        )

    def register_file(
        self,
        *,
        run_id: str,
        path: str | Path,
        artifact_type: ArtifactType,
        test_result_id: str | None = None,
        display_name: str | None = None,
        evidence_state: EvidenceState = EvidenceState.COMPLETE,
        sensitivity_class: str = "INTERNAL",
        retain_until: datetime | None = None,
        expected_sha256: str | None = None,
        expected_size_bytes: int | None = None,
    ) -> Artifact:
        if self.run_repository.get(run_id) is None:
            raise ValueError(f"Run not found: {run_id}")
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(file_path)
        if not sensitivity_class.strip():
            raise ValueError("sensitivity_class must not be empty")

        digest = hashlib.sha256()
        size = 0
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        sha256 = digest.hexdigest()
        if expected_size_bytes is not None and size != expected_size_bytes:
            raise ValueError(f"artifact size mismatch: expected {expected_size_bytes}, got {size}")
        if expected_sha256 is not None and sha256.lower() != expected_sha256.lower():
            raise ValueError("artifact sha256 mismatch")

        artifact = Artifact(
            artifact_id=self.id_generator(),
            run_id=run_id,
            artifact_type=artifact_type,
            path=str(file_path),
            sha256=sha256,
            size_bytes=size,
            evidence_state=evidence_state,
            test_result_id=test_result_id,
            display_name=display_name or file_path.name,
            created_at=self.clock(),
            sensitivity_class=sensitivity_class,
            retain_until=retain_until,
        )
        self.artifact_repository.save(artifact)
        self.event_repository.append(
            LifecycleEvent(
                event_id=self.id_generator(),
                run_id=run_id,
                event_type="ARTIFACT_CREATED",
                occurred_at=artifact.created_at or self.clock(),
                test_result_id=test_result_id,
                details={
                    "artifact_id": artifact.artifact_id,
                    "artifact_type": artifact.artifact_type.value,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                },
            )
        )
        return artifact

    def verify(self, artifact_id: str) -> bool:
        artifact = self.artifact_repository.get(artifact_id)
        if artifact is None:
            raise ValueError(f"Artifact not found: {artifact_id}")
        file_path = Path(artifact.path)
        if not file_path.is_file():
            return False
        if file_path.stat().st_size != artifact.size_bytes:
            return False
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().lower() == artifact.sha256.lower()

    def list_for_run(self, run_id: str) -> list[Artifact]:
        return self.artifact_repository.list_for_run(run_id)
