import json
from pathlib import Path

from lib.repositories import SQLiteDatabase
from lib.services import ArtifactService, DiagnosticBundleService, ReproductionManifestService, RunService, TestRegistry


def test_reproduction_manifest_is_created(tmp_path):
    database = SQLiteDatabase(tmp_path / "runner.db")
    service = RunService.from_sqlite(database)
    run, _ = service.create_run(
        firmware_version="v1.0",
        lab_id="lab",
        validation_profile="Full",
        selected_tests=["t"],
        test_definition_versions={"t": "1.0"},
        resolved_config={"device_id": "client_vm"},
        repository_commit="abc",
    )
    manifest = ReproductionManifestService(
        test_registry=TestRegistry.default(),
        root=tmp_path,
    ).create(run.run_id, run, tmp_path / "reproduction")
    assert manifest.manifest_path.is_file()
    payload = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == run.run_id
    assert payload["configuration_hash"] == run.configuration_hash


def test_diagnostic_bundle_contains_manifest(tmp_path):
    database = SQLiteDatabase(tmp_path / "runner.db")
    service = RunService.from_sqlite(database)
    run, _ = service.create_run(
        firmware_version="v1.0",
        lab_id="lab",
        validation_profile="Full",
        selected_tests=["t"],
        test_definition_versions={"t": "1.0"},
        resolved_config={"device_id": "client_vm"},
        repository_commit="abc",
    )
    artifact_service = ArtifactService.from_sqlite(database)
    bundle = DiagnosticBundleService(
        artifact_service=artifact_service,
        results_root=tmp_path / "results",
    ).build(run_id=run.run_id, reason="test diagnostic")
    assert bundle.archive_path.is_file()
    assert bundle.sha256
