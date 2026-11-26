"""Persisted, Vault-scoped observations from registered network-emulator providers."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import secrets
from typing import Any, Mapping


class ProviderObservationError(ValueError):
    """Invalid provider observation or unavailable provider binding."""


class ProviderObservationNotFound(LookupError):
    """Provider binding or observation is outside the requested Lab scope."""


class ProviderObservationService:
    """Collect real provider health, version, resource and capture capability observations.

    Provider construction and credentials stay behind TopologyApplyService's
    registry-backed ProviderSessionService. This class never accepts endpoint
    URLs, credentials, provider identifiers or measurement data from a client.
    """

    SCHEMA_VERSION = "1.0"
    MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
    MAX_COMPUTES = 128

    _VERSION_FIELDS = ("version", "local", "release", "build", "edition", "capabilities")
    _HEALTH_FIELDS = ("status", "observed_at", "version")
    _RESOURCE_FIELDS = (
        "compute_observation", "licensing_observation", "licensing", "observed_at",
    )
    _COMPUTE_FIELDS = (
        "compute_id", "name", "connected", "state", "cpu_usage_percent",
        "memory_usage_percent", "cpu_cores_total", "memory_gb_total",
    )
    _METRIC_FIELDS = {
        "cpu_usage_percent": ("cpu_usage_percent", "%", 0.0, 100.0),
        "memory_usage_percent": ("memory_usage_percent", "%", 0.0, 100.0),
        "cpu_cores_total": ("cpu_cores_total", "cores", 0.0, None),
        "memory_gb_total": ("memory_gb_total", "GiB", 0.0, None),
    }

    def __init__(self, database, topology_apply, *, clock=None) -> None:
        self.database = database
        self.topology_apply = topology_apply
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _canonical(value: object) -> str:
        try:
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ProviderObservationError("provider observation is not finite JSON data") from exc

    def _now(self) -> str:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ProviderObservationError("observation clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def _safe_scalar(cls, value: object, *, field: str) -> str | int | float | bool | None:
        if value is None or isinstance(value, (str, bool, int)):
            if isinstance(value, str) and (len(value) > 256 or any(ord(ch) < 32 for ch in value)):
                raise ProviderObservationError(f"provider {field} contains unsafe text")
            return value
        if isinstance(value, float) and math.isfinite(value):
            return value
        raise ProviderObservationError(f"provider {field} must be a finite scalar value")

    @classmethod
    def _safe_version(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ProviderObservationError("provider version observation is not an object")
        result = {}
        for key in cls._VERSION_FIELDS:
            if key not in value:
                continue
            field_value = value[key]
            if key == "capabilities" and isinstance(field_value, list):
                result[key] = [
                    str(item)[:128] for item in field_value
                    if isinstance(item, (str, int))
                ][:128]
            elif isinstance(field_value, (str, int, float, bool)) or field_value is None:
                result[key] = cls._safe_scalar(field_value, field="version." + key)
        return result

    @classmethod
    def _safe_health(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ProviderObservationError("provider health observation is not an object")
        result = {}
        for key in cls._HEALTH_FIELDS:
            if key not in value:
                continue
            if key == "version":
                result[key] = cls._safe_version(value[key])
            elif isinstance(value[key], (str, int, float, bool)) or value[key] is None:
                result[key] = cls._safe_scalar(value[key], field="health." + key)
        return result

    @classmethod
    def _safe_resources(cls, value: object, *, source: str, captured_at: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not isinstance(value, Mapping) or not isinstance(value.get("computes"), list):
            raise ProviderObservationError("provider resource observation has no compute array")
        raw_computes = value["computes"]
        if len(raw_computes) > cls.MAX_COMPUTES:
            raise ProviderObservationError("provider compute observation exceeds the 128-record limit")
        computes = []
        metrics = []
        for index, raw in enumerate(raw_computes):
            if not isinstance(raw, Mapping):
                raise ProviderObservationError(f"provider compute[{index}] is not an object")
            compute = {}
            for key in cls._COMPUTE_FIELDS:
                if key not in raw:
                    continue
                item = raw[key]
                if key == "connected":
                    if isinstance(item, bool):
                        compute[key] = item
                elif key in {"cpu_usage_percent", "memory_usage_percent", "cpu_cores_total", "memory_gb_total"}:
                    if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
                        continue
                    metric_name, unit, minimum, maximum = cls._METRIC_FIELDS[key]
                    numeric = float(item)
                    if numeric < minimum or (maximum is not None and numeric > maximum):
                        continue
                    compute[key] = numeric
                    metrics.append({
                        "name": metric_name, "value": numeric, "unit": unit,
                        "compute_id": str(raw.get("compute_id") or "unknown")[:128],
                        "compute_name": str(raw.get("name") or raw.get("compute_id") or "Compute")[:120],
                        "source": source + ".get_resource_availability",
                        "captured_at": captured_at,
                    })
                elif isinstance(item, (str, int, float)) or item is None:
                    compute[key] = cls._safe_scalar(item, field="compute." + key)
            computes.append(compute)

        safe = {"computes": computes}
        for key in cls._RESOURCE_FIELDS:
            if key not in value:
                continue
            item = value[key]
            if key == "licensing" and isinstance(item, Mapping):
                safe[key] = {
                    str(name)[:64]: cls._safe_scalar(entry, field="licensing." + str(name))
                    for name, entry in list(item.items())[:64]
                    if isinstance(entry, (str, int, float, bool)) or entry is None
                }
            elif isinstance(item, (str, int, float, bool)) or item is None:
                safe[key] = cls._safe_scalar(item, field="resources." + key)
        return safe, metrics

    @classmethod
    def _safe_capture_support(cls, provider: object, provider_id: str, topology_apply) -> dict[str, Any]:
        try:
            descriptor = topology_apply.provider_registry.descriptor(provider_id)
            capabilities = set(descriptor.capability_ids)
        except Exception:
            capabilities = set()
        if "packet_capture.supported" not in capabilities:
            return {
                "supported": False, "scope": "none",
                "observation": "NOT_SUPPORTED",
                "reason": "The registered provider adapter does not declare packet-capture support",
            }
        raw = provider.capture_support()
        if not isinstance(raw, Mapping):
            return {"supported": None, "scope": "unknown", "observation": "INVALID"}
        result = {
            "supported": raw.get("supported") if isinstance(raw.get("supported"), bool) else None,
            "scope": str(raw.get("scope") or "unknown")[:32],
            "observation": "OBSERVED",
        }
        for key in ("reason", "start_path", "stop_path", "readiness"):
            value = raw.get(key)
            if isinstance(value, str):
                result[key] = value[:256]
            elif key == "readiness" and isinstance(value, Mapping):
                result[key] = {
                    str(name)[:64]: cls._safe_scalar(item, field="capture.readiness")
                    for name, item in list(value.items())[:64]
                    if isinstance(item, (str, int, float, bool)) or item is None
                }
        return result

    @staticmethod
    def _validate_actor(actor: object) -> str:
        result = str(actor or "").strip()
        if not result or len(result) > 128 or any(ord(ch) < 33 for ch in result):
            raise ProviderObservationError("actor must contain 1 to 128 printable characters")
        return result

    def _persist(self, binding: Mapping[str, Any], payload: Mapping[str, Any], *, actor: str) -> dict[str, Any]:
        encoded = self._canonical(payload)
        if len(encoded.encode("utf-8")) > self.MAX_PAYLOAD_BYTES:
            raise ProviderObservationError("provider observation exceeds two MiB")
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        observation_id = "pobs_" + secrets.token_hex(12)
        created_at = self._now()
        with self.database.transaction(immediate=True) as connection:
            current = connection.execute(
                """SELECT 1 FROM gns3_lab_bindings b
                   JOIN labs l ON l.project_id=b.project_id AND l.lab_id=b.lab_id
                   WHERE b.binding_id=? AND b.project_id=? AND b.lab_id=?
                     AND b.provider_id=? AND b.status='ACTIVE' AND l.status='ACTIVE'""",
                (binding["binding_id"], binding["project_id"], binding["lab_id"], binding["provider_id"]),
            ).fetchone()
            if current is None:
                raise ProviderObservationNotFound("provider binding is no longer active in the selected Project/Lab")
            connection.execute(
                """INSERT INTO provider_observation_snapshots(
                    observation_id,project_id,lab_id,binding_id,provider_id,observed_at,
                    payload_json,payload_sha256,observed_by,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    observation_id, binding["project_id"], binding["lab_id"],
                    binding["binding_id"], binding["provider_id"], payload["observed_at"],
                    encoded, digest, actor, created_at,
                ),
            )
            connection.execute(
                """INSERT INTO audit_events(
                    audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    "AUD-" + secrets.token_hex(12), actor, "PROVIDER_OBSERVATION_RECORDED",
                    "PROVIDER_OBSERVATION", observation_id,
                    json.dumps({
                        "project_id": binding["project_id"], "lab_id": binding["lab_id"],
                        "provider_id": binding["provider_id"], "payload_sha256": digest,
                        "status": payload["status"],
                    }, sort_keys=True, separators=(",", ":")),
                    created_at,
                ),
            )
        return {
            "observation_id": observation_id, "project_id": binding["project_id"],
            "lab_id": binding["lab_id"], "binding_id": binding["binding_id"],
            "provider_id": binding["provider_id"], "observed_at": payload["observed_at"],
            "created_at": created_at, "payload_sha256": digest, "snapshot": dict(payload),
        }

    def capture(self, lab_id: str, *, actor: str) -> dict[str, Any]:
        actor = self._validate_actor(actor)
        binding = self.topology_apply.get_binding(lab_id)
        if binding is None:
            raise ProviderObservationNotFound("an active provider binding is required for this Lab")
        provider_id = str(binding.get("provider_id") or "").lower()
        if provider_id not in {"gns3", "cml", "eve-ng"}:
            raise ProviderObservationError("provider binding identifies an unsupported provider adapter")
        source = "provider." + provider_id
        try:
            self.topology_apply._require_provider_capability(provider_id, "connection.health.read")
            self.topology_apply._require_provider_capability(provider_id, "controller.version.read")
            self.topology_apply._require_provider_capability(provider_id, "resources.availability.read")

            def observe(provider):
                health = self._safe_health(provider.health_check())
                version = self._safe_version(provider.version())
                resources, metrics = self._safe_resources(
                    provider.get_resource_availability(), source=source,
                    captured_at=str(health.get("observed_at") or self._now()),
                )
                capture_support = self._safe_capture_support(provider, provider_id, self.topology_apply)
                observed_at = resources.get("observed_at") or health.get("observed_at")
                timestamp_source = "PROVIDER"
                if not isinstance(observed_at, str):
                    observed_at = self._now()
                    timestamp_source = "COLLECTOR"
                try:
                    parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                    if parsed.tzinfo is None or parsed.utcoffset() is None:
                        raise ValueError
                    observed_at = parsed.astimezone(timezone.utc).isoformat()
                except ValueError:
                    observed_at = self._now()
                    timestamp_source = "COLLECTOR"
                for metric in metrics:
                    metric["captured_at"] = observed_at
                return {
                    "schema_version": self.SCHEMA_VERSION, "status": str(health.get("status") or "UNKNOWN").upper(),
                    "provider_id": provider_id, "project_id": binding["project_id"], "lab_id": lab_id,
                    "source": source, "timestamp_source": timestamp_source,
                    "observed_at": observed_at, "health": health, "version": version,
                    "resources": resources, "metrics": metrics, "capture_support": capture_support,
                }

            payload = self.topology_apply._with_provider(binding, actor, observe)
        except Exception as exc:
            payload = {
                "schema_version": self.SCHEMA_VERSION, "status": "UNAVAILABLE",
                "provider_id": provider_id, "project_id": binding["project_id"], "lab_id": lab_id,
                "source": source, "timestamp_source": "COLLECTOR", "observed_at": self._now(),
                "health": {"status": "UNAVAILABLE"},
                "version": {}, "resources": {"computes": []}, "metrics": [],
                "capture_support": {"supported": False, "scope": "unknown", "observation": "UNAVAILABLE"},
                "failure": {"error_type": type(exc).__name__},
            }
        return self._persist(binding, payload, actor=actor)

    @classmethod
    def _serialize(cls, row) -> dict[str, Any]:
        encoded = row["payload_json"]
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if digest != row["payload_sha256"]:
            raise ProviderObservationError("stored provider observation failed its SHA-256 integrity check")
        try:
            payload = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ProviderObservationError("stored provider observation is invalid JSON") from exc
        return {
            "observation_id": row["observation_id"], "project_id": row["project_id"],
            "lab_id": row["lab_id"], "binding_id": row["binding_id"],
            "provider_id": row["provider_id"], "observed_at": row["observed_at"],
            "created_at": row["created_at"], "payload_sha256": digest,
            "observed_by": row["observed_by"], "snapshot": payload,
        }

    def list_for_lab(self, lab_id: str, *, limit: int = 40) -> list[dict[str, Any]]:
        if not isinstance(lab_id, str) or not lab_id.strip():
            raise ProviderObservationError("lab_id must not be empty")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ProviderObservationError("limit must be an integer")
        limit = max(1, min(limit, 100))
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM provider_observation_snapshots
                   WHERE lab_id=? ORDER BY observed_at DESC,observation_id DESC LIMIT ?""",
                (lab_id, limit),
            ).fetchall()
        return [self._serialize(row) for row in rows]
