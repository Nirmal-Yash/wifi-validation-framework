from pathlib import Path

from lib.services.doctor import RunnerDoctor
from lib.services.release_manifest import ReleaseManifestService


def test_release_manifest_public_contract(tmp_path):
    assert ReleaseManifestService(tmp_path).root == tmp_path.resolve()


def test_doctor_has_core_checks_and_distinguishes_unchecked(tmp_path, monkeypatch):
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED", "0")
    report = RunnerDoctor(tmp_path).run()
    checks = {check.check_id: check for check in report.checks}

    assert {"python", "tool:git", "tool:pytest", "authentication"} <= set(checks)
    assert checks["lab-tools"].status == "NOT_CHECKED"
    assert checks["dashboard:runtime"].status == "NOT_CHECKED"
    assert not (tmp_path / "results").exists()


def test_release_manifest_schema_is_stable():
    payload = ReleaseManifestService(Path(__file__).resolve().parents[1]).manifest()
    assert payload["schema_version"] == "netregress-release-manifest.v3"
    assert payload["source"]["commit"]
    assert payload["tracked_file_count"] > 0
    assert payload["required_paths_present"] is True
    assert "generated_at" not in payload
    assert "dependencies" in payload
    assert "production_reproducible" in payload
    assert payload["application"]["version"] is None
    assert payload["application"]["version_status"] == "NOT_DECLARED_IN_REPOSITORY_METADATA"
    dependencies = payload["dependencies"]
    assert dependencies["lockfiles_present"] is True
    assert dependencies["lockfiles_valid"] is True
    assert dependencies["runtime_complete"] is True
    assert dependencies["python"]["direct_dependencies_pinned"] is True
    # Python/npm application dependencies are locked, but the complete
    # desktop build graph remains explicitly incomplete until both build locks exist.
    assert dependencies["build_lockfiles_present"] is False
    assert dependencies["desktop_build"]["lockfile_valid"] is False
    assert dependencies["rust"]["lockfile_valid"] is False
    assert dependencies["status"] == "INCOMPLETE_BUILD_LOCKFILES"
    assert dependencies["complete"] is False
    assert payload["application"]["version"] == "0.1.0"
    assert payload["application"]["version_status"] == "DECLARED_IN_TAURI_CONFIGURATION"
    assert payload["production_reproducible"] is False
