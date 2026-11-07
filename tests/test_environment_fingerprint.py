from __future__ import annotations

import pytest

from lib.services.environment_fingerprint import EnvironmentFingerprintService


def test_fingerprint_is_stable_for_same_identity_inputs(tmp_path):
    service = EnvironmentFingerprintService(tmp_path)
    first = service.capture(
        lab_id="lab",
        configuration_hash="cfg",
        topology={"ap": "ap"},
        device_identity={"client": "c"},
        observations={"health": "healthy"},
    )
    second = service.capture(
        lab_id="lab",
        configuration_hash="cfg",
        topology={"ap": "ap"},
        device_identity={"client": "c"},
        observations={"health": "healthy"},
    )
    assert first.fingerprint == second.fingerprint


def test_volatile_observations_are_preserved_but_not_hashed(tmp_path):
    service = EnvironmentFingerprintService(tmp_path)
    first = service.capture(
        lab_id="lab",
        configuration_hash="cfg",
        topology={"ap": "ap"},
        device_identity={"client": "c"},
        observations={"rssi": -45, "health": "healthy"},
    )
    second = service.capture(
        lab_id="lab",
        configuration_hash="cfg",
        topology={"ap": "ap"},
        device_identity={"client": "c"},
        observations={"rssi": -72, "health": "degraded"},
    )
    assert first.fingerprint == second.fingerprint
    assert first.payload["observations"]["rssi"] == -45
    assert second.payload["observations"]["rssi"] == -72


def test_stable_identity_changes_fingerprint(tmp_path):
    service = EnvironmentFingerprintService(tmp_path)
    first = service.capture(lab_id="lab-a", configuration_hash="cfg")
    second = service.capture(lab_id="lab-b", configuration_hash="cfg")
    assert first.fingerprint != second.fingerprint


def test_fingerprint_detaches_and_freezes_nested_input(tmp_path):
    service = EnvironmentFingerprintService(tmp_path)
    topology = {"nodes": [{"name": "ap"}]}
    result = service.capture(
        lab_id="lab",
        configuration_hash="cfg",
        topology=topology,
    )
    topology["nodes"][0]["name"] = "mutated"
    assert result.payload["topology"]["nodes"][0]["name"] == "ap"
    with pytest.raises(TypeError, match="immutable"):
        result.payload["topology"]["nodes"][0]["name"] = "blocked"


def test_non_finite_observations_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="NaN or infinity"):
        EnvironmentFingerprintService(tmp_path).capture(
            lab_id="lab",
            configuration_hash="cfg",
            observations={"temperature": float("nan")},
        )
