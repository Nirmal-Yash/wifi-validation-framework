from lib.services.environment_fingerprint import EnvironmentFingerprintService

def test_fingerprint_is_stable_for_same_inputs(tmp_path):
    service=EnvironmentFingerprintService(tmp_path)
    a=service.capture(lab_id="lab",configuration_hash="cfg",topology={"ap":"ap"},device_identity={"client":"c"},observations={"class":"VIRTUAL_WIFI"})
    b=service.capture(lab_id="lab",configuration_hash="cfg",topology={"ap":"ap"},device_identity={"client":"c"},observations={"class":"VIRTUAL_WIFI"})
    assert a.fingerprint==b.fingerprint
