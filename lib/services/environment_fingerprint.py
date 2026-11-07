from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import platform
import socket
import subprocess
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class EnvironmentFingerprint:
    fingerprint: str
    captured_at: datetime
    payload: Mapping[str, Any]


class _FrozenList(list):
    def _immutable(self, *args, **kwargs):
        raise TypeError("environment fingerprint payload is immutable")

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


def _normalise(value: Any, path: str) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"{path} keys must be non-empty strings")
            result[key] = _normalise(child, f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_normalise(child, f"{path}[]") for child in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain NaN or infinity")
        return value
    raise TypeError(f"{path} contains unsupported value type: {type(value).__name__}")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze(child) for child in value)
    return value


class _FrozenDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError("environment fingerprint payload is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class EnvironmentFingerprintService:
    """Capture stable host/lab identity separately from volatile observations.

    The digest covers only stable identity inputs. Observations are retained in
    the payload for diagnostics but do not cause an otherwise identical
    environment to acquire a different identity on every health check.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def capture(
        self,
        *,
        lab_id: str,
        configuration_hash: str,
        topology: Mapping[str, Any] | None = None,
        device_identity: Mapping[str, Any] | None = None,
        observations: Mapping[str, Any] | None = None,
    ) -> EnvironmentFingerprint:
        if not isinstance(lab_id, str) or not lab_id.strip():
            raise ValueError("lab_id must be a non-empty string")
        if not isinstance(configuration_hash, str) or not configuration_hash.strip():
            raise ValueError("configuration_hash must be a non-empty string")

        identity_payload = {
            "fingerprint_version": 1,
            "lab_id": lab_id,
            "configuration_hash": configuration_hash,
            "host": {
                "hostname": socket.gethostname(),
                "os": platform.platform(),
                "kernel": platform.release(),
                "python": platform.python_version(),
                "architecture": platform.machine(),
            },
            "repository_commit": self._git_commit(),
            "interfaces": self._interfaces(),
            "topology": _normalise(topology or {}, "topology"),
            "device_identity": _normalise(device_identity or {}, "device_identity"),
        }
        observation_payload = _normalise(observations or {}, "observations")
        canonical = json.dumps(
            identity_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()

        payload = dict(identity_payload)
        payload["observations"] = observation_payload
        return EnvironmentFingerprint(
            fingerprint=digest,
            captured_at=datetime.now(timezone.utc),
            payload=_freeze(payload),
        )

    def _git_commit(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            return result.stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    @staticmethod
    def _interfaces() -> tuple[str, ...]:
        path = Path("/sys/class/net")
        try:
            return tuple(sorted(item.name for item in path.iterdir()))
        except OSError:
            return ()
