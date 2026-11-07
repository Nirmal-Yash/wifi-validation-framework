from __future__ import annotations

import pytest

from lib.services.configuration import ConfigurationResolver


def test_precedence_and_provenance():
    result = ConfigurationResolver().resolve(
        defaults={"x": 0, "nested": {"a": 1}},
        environment={"x": 1},
        lab={"x": 2},
        device={"x": 3},
        run={"x": 4, "nested": {"a": 4}},
        test_override={"x": 5},
    )
    assert result.values["x"] == 5
    assert result.values["nested"]["a"] == 4
    assert result.provenance["x"] == (
        "defaults", "environment", "lab", "device", "run", "test_override"
    )
    assert result.provenance["nested.a"] == ("defaults", "run")


def test_nested_values_are_detached_and_immutable():
    source = {"wifi": {"ssid": "lab", "channels": [1, 6, 11]}}
    result = ConfigurationResolver().resolve(defaults=source)
    source["wifi"]["ssid"] = "changed"
    source["wifi"]["channels"].append(36)

    assert result.values["wifi"]["ssid"] == "lab"
    assert list(result.values["wifi"]["channels"]) == [1, 6, 11]
    with pytest.raises(TypeError, match="immutable"):
        result.values["wifi"]["ssid"] = "mutated"
    with pytest.raises(TypeError, match="immutable"):
        result.values["wifi"]["channels"].append(36)


def test_nested_provenance_is_cleared_when_parent_is_replaced():
    result = ConfigurationResolver().resolve(
        defaults={"wifi": {"ssid": "lab", "security": {"psk": "secret"}}},
        run={"wifi": "disabled"},
    )
    assert result.values["wifi"] == "disabled"
    assert "wifi.ssid" not in result.provenance
    assert "wifi.security.psk" not in result.provenance
    assert result.provenance["wifi"] == ("run",)


def test_configuration_hash_is_order_independent_and_uses_canonical_json():
    resolver = ConfigurationResolver()
    first = resolver.resolve(defaults={"b": 2, "a": {"y": 1, "x": 3}})
    second = resolver.resolve(defaults={"a": {"x": 3, "y": 1}, "b": 2})
    assert first.configuration_hash == second.configuration_hash


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_configuration_values_are_rejected(bad):
    with pytest.raises(ValueError, match="NaN or infinity"):
        ConfigurationResolver().resolve(defaults={"threshold": bad})


def test_unknown_layers_and_non_object_sources_are_rejected():
    resolver = ConfigurationResolver()
    with pytest.raises(ValueError, match="unknown configuration layer"):
        resolver.resolve(defaults={}, tenant={"id": "one"})
    with pytest.raises(ValueError, match="must be an object"):
        resolver.resolve(environment=["not", "an", "object"])


def test_environment_json_must_be_a_json_object(monkeypatch):
    monkeypatch.setenv("NETREGRESS_CONFIG_JSON", "[1,2]")
    with pytest.raises(ValueError, match="must be an object"):
        ConfigurationResolver.environment_json()
    monkeypatch.setenv("NETREGRESS_CONFIG_JSON", "{invalid")
    with pytest.raises(ValueError, match="invalid JSON"):
        ConfigurationResolver.environment_json()


def test_provenance_resets_when_configuration_shape_changes():
    result = ConfigurationResolver().resolve(
        defaults={"wifi": "disabled"},
        run={"wifi": {"ssid": "lab"}},
        test_override={"wifi": {"channel": 6}},
    )
    assert result.values["wifi"] == {"ssid": "lab", "channel": 6}
    assert result.provenance["wifi.ssid"] == ("run",)
    assert result.provenance["wifi.channel"] == ("test_override",)
    assert "wifi" not in result.provenance
