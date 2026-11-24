"""Shared bounded metadata validation for native topology artifacts."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

_SECRET_PARTS = (
    "password", "passwd", "secret", "token", "private_key",
    "privatekey", "api_key", "apikey", "psk", "credential",
)
_NAMESPACE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


class MetadataValidationError(ValueError):
    """Raised when bounded, non-secret metadata cannot be canonicalized."""


def canonical_json(value: Any, *, maximum_bytes: int) -> tuple[str, str]:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise MetadataValidationError("metadata must contain finite JSON values") from exc
    payload = encoded.encode("utf-8")
    if len(payload) > maximum_bytes:
        raise MetadataValidationError(f"canonical JSON exceeds the {maximum_bytes}-byte limit")
    return encoded, hashlib.sha256(payload).hexdigest()


def bounded_json_value(
    value: Any,
    *,
    maximum_bytes: int,
    maximum_depth: int = 8,
    maximum_items: int = 2048,
    maximum_string: int = 4096,
    reject_secrets: bool = True,
) -> Any:
    """Copy JSON-compatible metadata while bounding depth, size and secret-like keys."""
    visited = 0

    def walk(item: Any, depth: int, path: str) -> Any:
        nonlocal visited
        visited += 1
        if visited > maximum_items:
            raise MetadataValidationError(f"{path} exceeds the {maximum_items}-item limit")
        if depth > maximum_depth:
            raise MetadataValidationError(f"{path} exceeds the {maximum_depth}-level nesting limit")
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, int):
            if abs(item) > 2**63 - 1:
                raise MetadataValidationError(f"{path} integer is outside the signed 64-bit range")
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise MetadataValidationError(f"{path} must be finite")
            return round(item, 8)
        if isinstance(item, str):
            if len(item) > maximum_string or any(ord(char) < 32 and char not in "\t\n\r" for char in item):
                raise MetadataValidationError(f"{path} contains an overlong or non-printable string")
            return item
        if isinstance(item, Mapping):
            if len(item) > 256:
                raise MetadataValidationError(f"{path} has too many object properties")
            result: dict[str, Any] = {}
            for raw_key, raw_value in item.items():
                if not isinstance(raw_key, str) or not raw_key or len(raw_key) > 96:
                    raise MetadataValidationError(f"{path} contains an invalid object key")
                if any(ord(char) < 33 for char in raw_key):
                    raise MetadataValidationError(f"{path} contains a non-printable object key")
                if reject_secrets and any(part in raw_key.lower() for part in _SECRET_PARTS):
                    raise MetadataValidationError(f"{path} contains a credential-like property name")
                if raw_key in result:
                    raise MetadataValidationError(f"{path} contains a duplicate property")
                result[raw_key] = walk(raw_value, depth + 1, f"{path}.{raw_key}")
            return result
        if isinstance(item, (list, tuple)):
            if len(item) > 512:
                raise MetadataValidationError(f"{path} has too many array items")
            return [walk(child, depth + 1, f"{path}[{index}]") for index, child in enumerate(item)]
        raise MetadataValidationError(f"{path} contains a value that is not JSON-compatible")

    result = walk(value, 0, "metadata")
    canonical_json(result, maximum_bytes=maximum_bytes)
    return result


def normalize_extensions(value: Any, *, field_name: str = "extensions") -> dict[str, Any]:
    """Validate namespaced extension objects without accepting arbitrary root fields."""
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > 16:
        raise MetadataValidationError(f"{field_name} must be a namespaced object with at most 16 entries")
    result: dict[str, Any] = {}
    for namespace, payload in value.items():
        if not isinstance(namespace, str) or not _NAMESPACE.fullmatch(namespace):
            raise MetadataValidationError(f"{field_name} contains an invalid namespace")
        if not isinstance(payload, Mapping):
            raise MetadataValidationError(f"{field_name}.{namespace} must be an object")
        result[namespace] = bounded_json_value(
            payload, maximum_bytes=100_000, maximum_depth=8,
            maximum_items=512, maximum_string=4096,
        )
    canonical_json(result, maximum_bytes=100_000)
    return result


def safe_relative_path(value: Any, *, field_name: str = "relative_path", maximum: int = 512) -> str:
    """Accept portable POSIX-relative asset paths, never absolute or parent-traversing paths."""
    if not isinstance(value, str):
        raise MetadataValidationError(f"{field_name} must be a relative POSIX path")
    if (
        not value or len(value) > maximum or value.startswith("/")
        or "\\" in value or "\x00" in value or ":" in value
        or any(ord(char) < 32 for char in value)
    ):
        raise MetadataValidationError(f"{field_name} must be a safe relative POSIX path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise MetadataValidationError(f"{field_name} must be a relative POSIX path and must not contain empty, dot or parent segments")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value:
        raise MetadataValidationError(f"{field_name} is not a canonical relative path")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
