from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import uuid

from lib.services.certification import CertificationMatrix
from lib.services.doctor import RunnerDoctor
from lib.services.release_manifest import ReleaseManifestService
from scripts.netregress_install import prepare_runtime_directories


def _make_install_checkout(root: Path) -> None:
    for relative in ("alembic", "configs", "dashboard", "frontend", "lib", "scripts"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
    (root / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")


def test_install_preflight_is_read_only(tmp_path):
    _make_install_checkout(tmp_path)

    report = prepare_runtime_directories(
        tmp_path,
        local_dir=tmp_path / ".private-state",
        check_only=True,
    )

    assert report["created"] == []
    assert {"results", "backups", "local_state", "local_logs"} <= set(report["missing"])
    assert not (tmp_path / "results").exists()
    assert not (tmp_path / ".private-state").exists()


def test_install_initializes_runtime_paths_with_private_state(tmp_path):
    _make_install_checkout(tmp_path)

    report = prepare_runtime_directories(
        tmp_path,
        local_dir=tmp_path / ".private-state",
    )

    assert set(report["created"]) == {
        "results",
        "reports",
        "captures",
        "backups",
        "diagnostics",
        "certification_evidence",
        "local_state",
        "local_logs",
    }
    assert (tmp_path / "results" / "backups").is_dir()
    assert (tmp_path / "results" / "certification-evidence").is_dir()
    assert os.stat(tmp_path / ".private-state").st_mode & 0o777 == 0o700
    assert os.stat(tmp_path / ".private-state" / "logs").st_mode & 0o777 == 0o700


def test_doctor_is_read_only_and_reports_unchecked_conditions(tmp_path, monkeypatch):
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED", "0")
    missing_database = tmp_path / "not-created.sqlite"

    report = RunnerDoctor(tmp_path).run(database=missing_database)
    statuses = {check.check_id: check.status for check in report.checks}

    assert {"python", "tool:git", "tool:pytest", "authentication"} <= set(statuses)
    assert statuses["lab-tools"] == "NOT_CHECKED"
    assert statuses["dashboard:runtime"] == "NOT_CHECKED"
    assert statuses["database:integrity"] == "WARNING"
    assert not missing_database.exists()
    assert not (tmp_path / "results").exists()


def test_doctor_uses_private_first_run_auth_files_without_exposing_them(tmp_path, monkeypatch):
    local = tmp_path / ".local"
    local.mkdir(mode=0o700)
    users = [{
        "username": "owner",
        "role": "OWNER",
        "password_hash": "not-a-plaintext-password-hash",
    }]
    auth_file = local / "netregress-auth.json"
    auth_file.write_text(json.dumps(users), encoding="utf-8")
    secret_file = local / "session-secret"
    secret_file.write_text("s" * 64, encoding="utf-8")
    auth_file.chmod(0o600)
    secret_file.chmod(0o600)
    local.chmod(0o700)

    monkeypatch.setenv("NETREGRESS_LOCAL_DIR", str(local))
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED", "1")
    monkeypatch.delenv("NETREGRESS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("NETREGRESS_AUTH_USERS_JSON", raising=False)

    report = RunnerDoctor(tmp_path).run()
    auth_check = next(check for check in report.checks if check.check_id == "authentication")

    assert auth_check.status == "PASS"
    assert "s" * 32 not in auth_check.message
    assert "not-a-plaintext-password-hash" not in auth_check.message


def test_doctor_rejects_group_or_world_readable_session_material(tmp_path, monkeypatch):
    local = tmp_path / ".local"
    local.mkdir(mode=0o700)
    (local / "netregress-auth.json").write_text(
        json.dumps([{"username": "owner", "role": "OWNER", "password_hash": "hash"}]),
        encoding="utf-8",
    )
    (local / "session-secret").write_text("s" * 64, encoding="utf-8")
    (local / "netregress-auth.json").chmod(0o644)
    (local / "session-secret").chmod(0o600)
    local.chmod(0o700)

    monkeypatch.setenv("NETREGRESS_LOCAL_DIR", str(local))
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED", "1")
    monkeypatch.delenv("NETREGRESS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("NETREGRESS_AUTH_USERS_JSON", raising=False)

    report = RunnerDoctor(tmp_path).run()
    auth_check = next(check for check in report.checks if check.check_id == "authentication")

    assert auth_check.status == "FAIL"
    assert "owner-readable only" in auth_check.message


def test_release_manifest_is_deterministic_and_verifiable(tmp_path):
    root = Path(__file__).resolve().parents[1]
    service = ReleaseManifestService(root)

    first = service.manifest()
    second = service.manifest()

    assert first == second
    assert first["schema_version"] == "netregress-release-manifest.v2"
    assert "generated_at" not in first
    assert first["dependencies"]["status"] in {
        "COMPLETE",
        "INCOMPLETE_TRANSITIVE_LOCKFILES",
    }
    assert first["application"]["version"] is None
    assert first["application"]["version_status"] == "NOT_DECLARED_IN_REPOSITORY_METADATA"
    assert first["application"]["frontend_package_version"]

    manifest_path = service.write_manifest(tmp_path / "release-manifest.json")
    verified = service.verify_manifest(manifest_path)
    assert verified["verified"] is True
    assert len(verified["manifest_sha256"]) == 64

    tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
    tampered["schema_version"] = "tampered"
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    assert service.verify_manifest(manifest_path)["verified"] is False


def _valid_certification_evidence(root: Path, evidence_dir: Path) -> dict:
    matrix = CertificationMatrix()
    current = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    fingerprint = hashlib.sha256(b"standalone-certification-test-environment").hexdigest()
    evidence = {}

    for scenario in matrix.scenarios:
        artifacts = []
        for index, evidence_type in enumerate(scenario.required_evidence_types):
            path = evidence_dir / f"{scenario.scenario_id}-{index}.evidence"
            path.write_text(
                f"{scenario.scenario_id}:{evidence_type}\n",
                encoding="utf-8",
            )
            artifacts.append({
                "type": evidence_type,
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })

        executions = []
        for index, execution_class in enumerate(matrix.required_execution_classes(scenario)):
            execution = {
                "execution_id": f"{scenario.scenario_id}-{execution_class.lower()}",
                "execution_class": execution_class,
                "status": "PASS",
                "executed_at": "2026-11-09T12:00:00+00:00",
                "source_commit": current,
                "environment_fingerprint": fingerprint,
                "command": "pytest --certification-scenario " + scenario.scenario_id,
                "evidence": artifacts,
            }
            if execution_class in {"REAL_LAB", "PROTECTED_TARGET"}:
                execution["operator"] = "test-operator"
                execution["approval_reference"] = "approved-maintenance-window-001"
            executions.append(execution)

        expected_lifecycle = scenario.expected_lifecycle.split("_OR_")[0]
        record = {
            "status": "PASS",
            "lifecycle": expected_lifecycle,
            "controls": list(scenario.required_controls),
            "executions": executions,
        }
        if scenario.expected_outcome is not None:
            record["outcome"] = scenario.expected_outcome
        evidence[scenario.scenario_id] = record

    return evidence


def test_certification_requires_all_execution_classes_and_verified_evidence(tmp_path):
    root = Path(__file__).resolve().parents[1]
    evidence_parent = root / "results" / "certification-evidence"
    evidence_parent.mkdir(parents=True, exist_ok=True)
    evidence_dir = evidence_parent / f"test-{uuid.uuid4().hex}"
    evidence_dir.mkdir()
    try:
        matrix = CertificationMatrix()
        evidence = _valid_certification_evidence(root, evidence_dir)

        accepted = matrix.evaluate_evidence(evidence, root=root)
        assert accepted.complete is True
        assert accepted.missing_scenarios == ()

        incomplete = json.loads(json.dumps(evidence))
        incomplete["real_lab_baseline"]["executions"] = [
            item for item in incomplete["real_lab_baseline"]["executions"]
            if item["execution_class"] != "REAL_LAB"
        ]
        rejected = matrix.evaluate_evidence(incomplete, root=root)
        assert rejected.complete is False
        assert "real_lab_baseline" in rejected.missing_scenarios
        assert any("REAL_LAB" in issue for issue in rejected.issues)
    finally:
        shutil.rmtree(evidence_dir, ignore_errors=True)


def test_certification_rejects_tampered_artifact_and_stale_source(tmp_path):
    root = Path(__file__).resolve().parents[1]
    evidence_parent = root / "results" / "certification-evidence"
    evidence_parent.mkdir(parents=True, exist_ok=True)
    evidence_dir = evidence_parent / f"test-{uuid.uuid4().hex}"
    evidence_dir.mkdir()
    try:
        matrix = CertificationMatrix()
        evidence = _valid_certification_evidence(root, evidence_dir)
        scenario = "real_lab_baseline"
        evidence_path = root / evidence[scenario]["executions"][0]["evidence"][0]["path"]
        evidence_path.write_text("tampered\n", encoding="utf-8")

        tampered = matrix.evaluate_evidence(evidence, root=root)
        assert tampered.complete is False
        assert scenario in tampered.missing_scenarios

        evidence = _valid_certification_evidence(root, evidence_dir)
        evidence[scenario]["executions"][0]["source_commit"] = "0" * 40
        stale = matrix.evaluate_evidence(evidence, root=root)
        assert stale.complete is False
        assert scenario in stale.missing_scenarios
    finally:
        shutil.rmtree(evidence_dir, ignore_errors=True)


def test_install_does_not_repair_unsafe_existing_local_permissions(tmp_path):
    _make_install_checkout(tmp_path)
    local = tmp_path / ".private-state"
    local.mkdir(mode=0o755)
    local.chmod(0o755)

    try:
        prepare_runtime_directories(tmp_path, local_dir=local)
    except PermissionError as exc:
        assert "owner-only access" in str(exc)
    else:
        raise AssertionError("unsafe existing local-state permissions must fail closed")

    assert os.stat(local).st_mode & 0o777 == 0o755


def test_install_rejects_runtime_directory_symlink(tmp_path):
    _make_install_checkout(tmp_path)
    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}"
    outside.mkdir()
    try:
        (tmp_path / "results").symlink_to(outside, target_is_directory=True)
        try:
            prepare_runtime_directories(tmp_path)
        except RuntimeError as exc:
            assert "must not be a symlink" in str(exc)
        else:
            raise AssertionError("runtime results symlink must be rejected")
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_doctor_reports_first_run_authentication_as_pending_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("NETREGRESS_LOCAL_DIR", str(tmp_path / ".local"))
    monkeypatch.delenv("NETREGRESS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("NETREGRESS_AUTH_USERS_JSON", raising=False)

    report = RunnerDoctor(tmp_path).run()
    auth_check = next(check for check in report.checks if check.check_id == "authentication")

    assert auth_check.status == "WARNING"
    assert "first-run OWNER setup is pending" in auth_check.message


def test_install_rejects_local_state_symlink(tmp_path):
    _make_install_checkout(tmp_path)
    target = tmp_path.parent / f"private-target-{uuid.uuid4().hex}"
    target.mkdir()
    link = tmp_path / ".private-state"
    try:
        link.symlink_to(target, target_is_directory=True)
        try:
            prepare_runtime_directories(tmp_path, local_dir=link)
        except RuntimeError as exc:
            assert "local-state directory must not be a symlink" in str(exc)
        else:
            raise AssertionError("local-state symlink must be rejected")
    finally:
        shutil.rmtree(target, ignore_errors=True)


def test_doctor_rejects_local_state_and_credential_symlinks(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "netregress-auth.json").write_text(
        json.dumps([{"username": "owner", "role": "OWNER", "password_hash": "hash"}]),
        encoding="utf-8",
    )
    (outside / "session-secret").write_text("s" * 64, encoding="utf-8")
    local_link = tmp_path / ".local-link"
    local_link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("NETREGRESS_LOCAL_DIR", str(local_link))
    report = RunnerDoctor(tmp_path).run()
    checks = {check.check_id: check for check in report.checks}
    assert checks["storage:local_state"].status == "FAIL"
    assert checks["authentication"].status != "PASS"

    local_link.unlink()
    local = tmp_path / ".local"
    local.mkdir(mode=0o700)
    external_users = tmp_path / "external-users.json"
    external_users.write_text(
        json.dumps([{"username": "owner", "role": "OWNER", "password_hash": "hash"}]),
        encoding="utf-8",
    )
    (local / "netregress-auth.json").symlink_to(external_users)
    (local / "session-secret").write_text("s" * 64, encoding="utf-8")
    (local / "session-secret").chmod(0o600)
    local.chmod(0o700)
    monkeypatch.setenv("NETREGRESS_LOCAL_DIR", str(local))
    report = RunnerDoctor(tmp_path).run()
    auth = next(check for check in report.checks if check.check_id == "authentication")
    assert auth.status == "FAIL"
    assert "must not be a symlink" in auth.message


def test_release_manifest_counts_only_tracked_dependency_lockfiles(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (tmp_path / "requirements.txt").write_text("Flask==3.0.0\\n", encoding="utf-8")
    (frontend / "package.json").write_text(
        json.dumps({"dependencies": {"react": "19.3.1"}, "devDependencies": {}}),
        encoding="utf-8",
    )
    (tmp_path / "requirements.lock").write_text("Flask==3.0.0\\n", encoding="utf-8")
    (frontend / "package-lock.json").write_text("{}\\n", encoding="utf-8")

    service = ReleaseManifestService(tmp_path)
    monkeypatch.setattr(
        service, "tracked_files",
        lambda: ("requirements.txt", "frontend/package.json"),
    )
    untracked = service._dependency_control()
    assert untracked["lockfiles_present"] is False
    assert untracked["python"]["transitive_lockfile"] is None
    assert untracked["frontend"]["transitive_lockfile"] is None

    monkeypatch.setattr(
        service, "tracked_files",
        lambda: (
            "requirements.txt", "requirements.lock",
            "frontend/package.json", "frontend/package-lock.json",
        ),
    )
    tracked = service._dependency_control()
    assert tracked["lockfiles_present"] is True
    assert tracked["python"]["transitive_lockfile"] == "requirements.lock"
    assert tracked["frontend"]["transitive_lockfile"] == "frontend/package-lock.json"


def test_dashboard_launcher_uses_committed_lock_only_and_fingerprints_install():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "start_dashboard.sh").read_text(encoding="utf-8")

    assert "frontend_install_fingerprint" in launcher
    assert "git ls-files --error-unmatch frontend/package-lock.json" in launcher
    assert "npm ci --no-audit" in launcher
    assert "npm install --no-package-lock" in launcher
    assert 'digest.update(bytes([0]))' in launcher
    assert r"printf '%s\n'" in launcher

def test_lab_reprovision_requires_explicit_test_mode_and_waits_for_clock():
    root = Path(__file__).resolve().parents[1]
    script = (root / "wifi_lab_reprovision_robust.sh").read_text(encoding="utf-8")

    assert 'RUN_TESTS_MODE="none"' in script
    assert "--run-ci-tests" in script
    assert "--run-real-lab-tests" in script
    assert "--run-full-suite" in script
    assert 'systemctl enable --now chrony' in script
    assert "chronyc waitsync 10 0.5" in script
    assert 'pytest -m real_lab tests/' in script
    assert 'NETREGRESS_CI_MODE=1' in script


def test_doctor_database_integrity_accepts_relative_database_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED", "0")

    database = Path("results") / "test_results.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE doctor_path_probe (id INTEGER PRIMARY KEY)")

    report = RunnerDoctor(tmp_path).run(database=database)
    checks = {check.check_id: check for check in report.checks}

    assert checks["database:integrity"].status == "PASS"
    assert "integrity_check=ok" in checks["database:integrity"].message
