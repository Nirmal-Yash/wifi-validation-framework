from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from typing import Any, Mapping


class FrozenDict(dict):
    """JSON-serializable dictionary that rejects normal mutation operations."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("resolved configuration is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class FrozenList(list):
    """JSON-serializable list that rejects normal mutation operations."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("resolved configuration is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


def _copy_config(value: Any, path: str = "configuration") -> Any:
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"{path} keys must be non-empty strings")
            copied[key] = _copy_config(child, f"{path}.{key}")
        return copied
    if isinstance(value, (list, tuple)):
        return [_copy_config(child, f"{path}[]") for child in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain NaN or infinity")
        return value
    raise TypeError(f"{path} contains unsupported value type: {type(value).__name__}")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenDict({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return FrozenList(_freeze(child) for child in value)
    return value


@dataclass(frozen=True, slots=True)
class ResolvedConfiguration:
    values: Mapping[str, Any]
    configuration_hash: str
    provenance: Mapping[str, tuple[str, ...]]


class ConfigurationResolver:
    """Merge configuration layers and retain per-key source provenance."""

    PRECEDENCE = (
        "defaults",
        "environment",
        "lab",
        "device",
        "run",
        "test_override",
    )

    def resolve(self, **sources: Mapping[str, Any] | None) -> ResolvedConfiguration:
        unknown = set(sources) - set(self.PRECEDENCE)
        if unknown:
            raise ValueError(f"unknown configuration layer(s): {', '.join(sorted(unknown))}")

        merged: dict[str, Any] = {}
        provenance: dict[str, list[str]] = {}

        def clear_descendants(path: str) -> None:
            prefix = path + "."
            for existing in tuple(provenance):
                if existing.startswith(prefix):
                    del provenance[existing]

        def merge_layer(
            destination: dict[str, Any],
            source: Mapping[str, Any],
            layer: str,
            prefix: str = "",
        ) -> None:
            for key, raw_value in source.items():
                if not isinstance(key, str) or not key.strip():
                    raise ValueError(f"{layer} configuration keys must be non-empty strings")
                path = f"{prefix}.{key}" if prefix else key
                value = _copy_config(raw_value, f"{layer}.{path}")
                if isinstance(value, dict):
                    current = destination.get(key)
                    if not isinstance(current, dict):
                        clear_descendants(path)
                        provenance.pop(path, None)
                        current = {}
                        destination[key] = current
                    if value:
                        merge_layer(current, value, layer, path)
                    elif not current:
                        provenance.setdefault(path, []).append(layer)
                else:
                    if isinstance(destination.get(key), dict):
                        clear_descendants(path)
                        provenance.pop(path, None)
                    destination[key] = value
                    provenance.setdefault(path, []).append(layer)

        for layer in self.PRECEDENCE:
            source = sources.get(layer)
            if source is None:
                continue
            if not isinstance(source, Mapping):
                raise ValueError(f"{layer} configuration must be an object")
            merge_layer(merged, source, layer)

        canonical = json.dumps(
            merged,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        frozen_provenance = {
            key: tuple(layers) for key, layers in provenance.items()
        }
        return ResolvedConfiguration(
            values=_freeze(merged),
            configuration_hash=digest,
            provenance=_freeze(frozen_provenance),
        )

    @staticmethod
    def environment_json() -> Mapping[str, Any]:
        raw = os.getenv("NETREGRESS_CONFIG_JSON", "{}") or "{}"
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"NETREGRESS_CONFIG_JSON is invalid JSON: {exc}") from exc
        if not isinstance(value, Mapping):
            raise ValueError("NETREGRESS_CONFIG_JSON must be an object")
        # Validate and detach from parser-owned objects before handing it to callers.
        return _freeze(_copy_config(value, "NETREGRESS_CONFIG_JSON"))
