from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from lib.domain import Artifact, ArtifactType, EvidenceState, LifecycleEvent
from lib.repositories import (
    ArtifactRepository,
    AttemptRepository,
    EventRepository,
    RunRepository,
    TestResultRepository,
    SQLiteArtifactRepository,
    SQLiteAttemptRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
    SQLiteTestResultRepository,
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
        test_result_repository: TestResultRepository | None = None,
        attempt_repository: AttemptRepository | None = None,
        id_generator=generate_ulid,
        clock=lambda: datetime.now(timezone.utc),
    ):
        self.artifact_repository = artifact_repository
        self.run_repository = run_repository
        self.event_repository = event_repository
        self.test_result_repository = test_result_repository
        self.attempt_repository = attempt_repository
        self.id_generator = id_generator
        self.clock = clock

    @classmethod
    def from_sqlite(cls, database: SQLiteDatabase, **kwargs):
        database.initialize()
        kwargs.setdefault("test_result_repository", SQLiteTestResultRepository(database))
        kwargs.setdefault("attempt_repository", SQLiteAttemptRepository(database))
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
        test_node_id: str | None = None,
        attempt_id: str | None = None,
        display_name: str | None = None,
        evidence_state: EvidenceState = EvidenceState.COMPLETE,
        sensitivity_class: str = "INTERNAL",
        retain_until: datetime | None = None,
        expected_sha256: str | None = None,
        expected_size_bytes: int | None = None,
        provenance: str = "NATIVE",
    ) -> Artifact:
        if self.run_repository.get(run_id) is None:
            raise ValueError(f"Run not found: {run_id}")
        if test_result_id is not None:
            if self.test_result_repository is None:
                raise ValueError("test_result_repository is required for TestResult-owned artifacts")
            test_result = self.test_result_repository.get(test_result_id)
            if test_result is None or test_result.run_id != run_id:
                raise ValueError("artifact TestResult must belong to the same Run")
            if test_node_id is not None and test_node_id != test_result.node_id:
                raise ValueError("artifact pytest node does not match its TestResult")
            if attempt_id is not None and attempt_id != test_result.attempt_id:
                raise ValueError("artifact Attempt does not match its TestResult")
            test_node_id = test_result.node_id
            attempt_id = test_result.attempt_id
        if attempt_id is not None:
            if self.attempt_repository is None:
                raise ValueError("attempt_repository is required for Attempt-owned artifacts")
            attempt = self.attempt_repository.get(attempt_id)
            if attempt is None or attempt.run_id != run_id:
                raise ValueError("artifact Attempt must belong to the same Run")
        if test_node_id is not None and attempt_id is None:
            raise ValueError("test-node-owned artifacts must identify their Attempt or TestResult")
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
            test_node_id=test_node_id,
            attempt_id=attempt_id,
            display_name=display_name or file_path.name,
            created_at=self.clock(),
            sensitivity_class=sensitivity_class,
            retain_until=retain_until,
            provenance=provenance,
        )
        self.artifact_repository.save(artifact)
        self.event_repository.append(
            LifecycleEvent(
                event_id=self.id_generator(),
                run_id=run_id,
                event_type="ARTIFACT_CREATED",
                occurred_at=artifact.created_at or self.clock(),
                attempt_id=attempt_id,
                test_result_id=test_result_id,
                details={
                    "artifact_id": artifact.artifact_id,
                    "test_node_id": artifact.test_node_id,
                    "attempt_id": artifact.attempt_id,
                    "artifact_type": artifact.artifact_type.value,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                },
            )
        )
        return artifact

    def _belongs_to_test(
        self,
        artifact,
        *,
        run_id: str,
        node_id: str,
        attempt_id: str | None,
    ) -> bool:
        """Resolve evidence ownership without allowing cross-Run/test/Attempt association."""
        if artifact.run_id != run_id:
            return False
        if artifact.attempt_id is not None and artifact.attempt_id != attempt_id:
            return False
        if artifact.test_node_id is not None and artifact.test_node_id != node_id:
            return False
        if artifact.test_result_id is not None:
            if self.test_result_repository is None:
                return False
            result = self.test_result_repository.get(artifact.test_result_id)
            return (
                result is not None
                and result.run_id == run_id
                and result.node_id == node_id
                and result.attempt_id == attempt_id
            )
        if artifact.test_node_id is not None:
            return artifact.attempt_id is not None and artifact.attempt_id == attempt_id
        if artifact.attempt_id is not None:
            return artifact.attempt_id == attempt_id
        return True

    def evaluate_test_evidence(
        self,
        *,
        run_id: str,
        node_id: str,
        required_types: tuple[ArtifactType, ...] | list[ArtifactType],
        attempt_id: str | None = None,
    ) -> EvidenceState:
        """Validate evidence owned by this test and Attempt, plus Run-level evidence."""
        required = set(required_types)
        if not required:
            return EvidenceState.NOT_REQUIRED

        matching = [
            artifact
            for artifact in self.list_for_run(run_id)
            if artifact.soft_deleted_at is None
            and artifact.artifact_type in required
            and self._belongs_to_test(
                artifact,
                run_id=run_id,
                node_id=node_id,
                attempt_id=attempt_id,
            )
        ]
        valid_types: set[ArtifactType] = set()
        incomplete = False
        invalid = False
        for artifact in matching:
            if artifact.evidence_state is EvidenceState.INVALID:
                invalid = True
                continue
            if artifact.evidence_state is not EvidenceState.COMPLETE:
                incomplete = True
                continue
            try:
                if not self.verify(artifact.artifact_id):
                    invalid = True
                    continue
            except Exception:
                invalid = True
                continue
            valid_types.add(artifact.artifact_type)

        if invalid:
            return EvidenceState.INVALID
        if incomplete or required - valid_types:
            return EvidenceState.INCOMPLETE
        return EvidenceState.COMPLETE

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
