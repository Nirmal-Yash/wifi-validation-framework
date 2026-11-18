from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest
from scripts.netregress_verify_desktop_artifacts import verify_desktop_artifacts
from lib.services.certification import CertificationMatrix

COMMIT = "a" * 40


def _artifact_tree(root):
    for os_version in ("ubuntu-22.04", "ubuntu-24.04"):
        build = root / f"netregress-linux-desktop-{os_version}-{COMMIT}"
        bundle = build / "src-tauri" / "target" / "release" / "bundle"
        (bundle / "deb").mkdir(parents=True)
        (bundle / "appimage").mkdir()
        (build / "release-output").mkdir(parents=True)
        packages = (bundle / "deb" / "runner.deb", bundle / "appimage" / "Runner.AppImage")
        for package in packages:
            package.write_bytes(package.name.encode())
        (bundle / "SHA256SUMS").write_text(
            "\n".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(bundle).as_posix()}" for p in packages) + "\n",
            encoding="utf-8",
        )
        (build / "release-output" / "netregress-source.spdx.json").write_text(
            json.dumps({"spdxVersion": "SPDX-2.3", "packages": [{
                "name": "library", "versionInfo": "1.0",
                "licenseDeclared": "MIT", "licenseConcluded": "NOASSERTION",
            }]}), encoding="utf-8",
        )


def test_exact_commit_checksums_and_attestations_for_four_packages(tmp_path):
    _artifact_tree(tmp_path)
    commands = []
    report = verify_desktop_artifacts(
        tmp_path, repository="owner/repo", source_commit=COMMIT,
        run_command=lambda command: commands.append(list(command)),
    )
    assert report["package_count"] == 4
    assert len(commands) == 8
    assert report["license_approval"] == "REQUIRED"
    assert report["license_review"]["ubuntu-22.04"]["review_required_count"] == 1


def test_checksum_mismatch_blocks_attestation_calls(tmp_path):
    _artifact_tree(tmp_path)
    next(tmp_path.rglob("runner.deb")).write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        verify_desktop_artifacts(
            tmp_path, repository="owner/repo", source_commit=COMMIT,
            run_command=lambda _cmd: pytest.fail("bad package must not be attested"),
        )


def test_certification_unknown_scenarios_and_unhashable_controls_fail_closed(tmp_path, monkeypatch):
    matrix = CertificationMatrix()
    monkeypatch.setattr(CertificationMatrix, "_current_commit", staticmethod(lambda _root: "b" * 40))
    result = matrix.evaluate_evidence({
        "extra": {"status": "PASS"},
        "healthy_run": {
            "status": "PASS", "lifecycle": "COMPLETED", "outcome": "VALIDATED",
            "controls": [{"unexpected": "object"}], "executions": [],
        },
    }, root=tmp_path)
    assert result.complete is False
    assert any("unknown scenario id: extra" in issue for issue in result.issues)
    assert any("missing controls" in issue for issue in result.issues)
