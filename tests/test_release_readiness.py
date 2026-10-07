from pathlib import Path
from lib.services.doctor import RunnerDoctor
from lib.services.release_manifest import ReleaseManifestService
def test_release_manifest_public_contract(tmp_path):
    assert ReleaseManifestService(tmp_path).root==tmp_path.resolve()
def test_doctor_has_core_checks(tmp_path,monkeypatch):
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED","0");ids={c.check_id for c in RunnerDoctor(tmp_path).run().checks};assert {"python","tool:git","tool:pytest","authentication"} <= ids
def test_release_manifest_schema_is_stable():
    payload=ReleaseManifestService(Path(__file__).resolve().parents[1]).manifest()
    assert payload["schema_version"]=="netregress-release-manifest.v1";assert payload["commit"];assert payload["tracked_file_count"]>0;assert payload["required_paths_present"] is True
