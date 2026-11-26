"""Project/Lab-scoped, evidence-backed network interface observations."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
from typing import Any, Mapping


class DeviceObservationError(ValueError):
    """A device observation could not be safely collected or verified."""


class DeviceObservationNotFound(LookupError):
    """The requested device observation is outside the selected scope."""


_INTERFACE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
_COUNTERS = (
    ("rx_bytes", "bytes"), ("rx_packets", "packets"),
    ("rx_errors", "errors"), ("rx_dropped", "packets"),
    ("tx_bytes", "bytes"), ("tx_packets", "packets"),
    ("tx_errors", "errors"), ("tx_dropped", "packets"),
)
_COMMAND = "ip -s -j link show"


class DeviceObservationService:
    """Collect read-only Linux interface counters through the secured Runner.

    The service only persists values returned by the target device. Missing
    fields stay absent; it never fabricates zeroes or derives rates from a
    single counter snapshot.
    """

    SCHEMA_VERSION = "1.0"
    MAX_INTERFACES = 128
    MAX_PAYLOAD_BYTES = 2 * 1024 * 1024

    def __init__(self, database, *, clock=None) -> None:
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _canonical(value: object) -> str:
        try:
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise DeviceObservationError("observation payload is not finite JSON data") from exc

    @staticmethod
    def _now(clock) -> str:
        value = clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise DeviceObservationError("observation clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def parse_ip_link_stats(cls, output: str) -> dict[str, Any]:
        if not isinstance(output, str):
            raise DeviceObservationError("target returned no interface statistics")
        if len(output.encode("utf-8")) > cls.MAX_PAYLOAD_BYTES:
            raise DeviceObservationError("target interface output exceeds the two MiB safety limit")
        if not output.strip():
            raise DeviceObservationError("target returned no interface statistics")
        try:
            raw_interfaces = json.loads(output)
        except json.JSONDecodeError as exc:
            raise DeviceObservationError("target returned invalid ip JSON") from exc
        if not isinstance(raw_interfaces, list) or not raw_interfaces:
            raise DeviceObservationError("ip JSON must contain a non-empty interface array")
        if len(raw_interfaces) > cls.MAX_INTERFACES:
            raise DeviceObservationError("interface observation exceeds the 128-interface limit")

        interfaces = []
        warnings = []
        for index, raw in enumerate(raw_interfaces):
            if not isinstance(raw, Mapping):
                raise DeviceObservationError(f"interface entry {index} is not an object")
            name = raw.get("ifname")
            if not isinstance(name, str) or not _INTERFACE.fullmatch(name):
                raise DeviceObservationError(f"interface entry {index} has an invalid interface name")
            stats64 = raw.get("stats64")
            stats32 = raw.get("stats")
            stats = stats64 if isinstance(stats64, Mapping) else stats32
            if not isinstance(stats, Mapping):
                warnings.append(f"{name}: driver did not expose interface counters")
                stats = {}

            counters: dict[str, int] = {}
            for direction in ("rx", "tx"):
                values = stats.get(direction)
                if not isinstance(values, Mapping):
                    continue
                for field, _unit in _COUNTERS:
                    prefix, metric = field.split("_", 1)
                    if prefix != direction or metric not in values:
                        continue
                    number = values[metric]
                    if isinstance(number, bool) or not isinstance(number, int) or number < 0 or number > 2**64 - 1:
                        warnings.append(f"{name}: invalid {field} counter was omitted")
                        continue
                    counters[field] = number

            ifindex = raw.get("ifindex")
            mtu = raw.get("mtu")
            if isinstance(ifindex, bool) or not isinstance(ifindex, int) or ifindex < 1:
                ifindex = None
            if isinstance(mtu, bool) or not isinstance(mtu, int) or mtu < 1:
                mtu = None
            flags = raw.get("flags")
            safe_flags = sorted({
                item for item in flags
                if isinstance(item, str) and re.fullmatch(r"[A-Z0-9_]{1,24}", item)
            }) if isinstance(flags, list) else []
            interfaces.append({
                "name": name, "ifindex": ifindex, "mtu": mtu,
                "flags": safe_flags, "counters": counters,
            })

        if not any(interface["counters"] for interface in interfaces):
            raise DeviceObservationError("no trustworthy interface counters were returned")
        return {"interfaces": interfaces, "warnings": warnings}

    @staticmethod
    def _audit(connection, actor: str, observation_id: str, device: Mapping[str, Any], digest: str, captured_at: str) -> None:
        connection.execute(
            """INSERT INTO audit_events(
                audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "AUD-" + secrets.token_hex(12), actor, "DEVICE_OBSERVATION_RECORDED",
                "DEVICE_OBSERVATION", observation_id,
                json.dumps({
                    "project_id": device["project_id"], "lab_id": device["lab_id"],
                    "device_id": device["device_id"], "payload_sha256": digest,
                }, sort_keys=True, separators=(",", ":")),
                captured_at,
            ),
        )

    def capture(self, device: Mapping[str, Any], command_runner, *, actor: str) -> dict[str, Any]:
        actor = str(actor or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise DeviceObservationError("actor must contain 1 to 128 printable characters")
        if not isinstance(device, Mapping) or not all(
            isinstance(device.get(key), str) and device[key].strip()
            for key in ("device_id", "project_id", "lab_id", "name")
        ):
            raise DeviceObservationError("an active Project/Lab-scoped managed Device is required")
        if device.get("status") != "ACTIVE":
            raise DeviceObservationError("archived Devices cannot be observed")

        try:
            result = command_runner.execute(
                device["device_id"], _COMMAND,
                command_category="device_observability",
                idempotent=True,
                privilege_mode="USER",
                connect_timeout_sec=10.0,
                execution_timeout_sec=30.0,
            )
        except Exception as exc:
            raise DeviceObservationError(
                "read-only device observation failed (" + type(exc).__name__ + ")"
            ) from exc
        if not getattr(result, "transport_succeeded", False):
            raise DeviceObservationError("SSH transport did not complete successfully")
        if getattr(result, "exit_code", None) != 0:
            raise DeviceObservationError("target ip command did not exit successfully")

        captured_at = self._now(self.clock)
        parsed = self.parse_ip_link_stats(result.stdout)
        counter_units = dict(_COUNTERS)
        observed_metrics = [
            {
                "metric": metric, "value": value, "unit": counter_units[metric],
                "interface": interface["name"], "source": _COMMAND,
                "captured_at": captured_at,
            }
            for interface in parsed["interfaces"]
            for metric, value in sorted(interface["counters"].items())
        ]
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "device_id": device["device_id"],
            "project_id": device["project_id"],
            "lab_id": device["lab_id"],
            "device_name": device["name"],
            "captured_at": captured_at,
            "source": "linux.ip-link-json",
            "command": _COMMAND,
            "interfaces": parsed["interfaces"],
            "metrics": observed_metrics,
            "warnings": parsed["warnings"],
        }
        encoded = self._canonical(payload)
        if len(encoded.encode("utf-8")) > self.MAX_PAYLOAD_BYTES:
            raise DeviceObservationError("observation payload exceeds two MiB")
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        observation_id = "obs_" + secrets.token_hex(12)
        created_at = self._now(self.clock)
        with self.database.transaction(immediate=True) as connection:
            valid_scope = connection.execute(
                """SELECT 1 FROM devices d JOIN labs l
                   ON l.project_id=d.project_id AND l.lab_id=d.lab_id
                   WHERE d.device_id=? AND d.project_id=? AND d.lab_id=?
                     AND d.status='ACTIVE' AND l.status='ACTIVE'""",
                (device["device_id"], device["project_id"], device["lab_id"]),
            ).fetchone()
            if valid_scope is None:
                raise DeviceObservationNotFound("Device is no longer active in this Project/Lab")
            connection.execute(
                """INSERT INTO device_observation_snapshots(
                    observation_id,project_id,lab_id,device_id,source,captured_at,
                    payload_json,payload_sha256,observed_by,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    observation_id, device["project_id"], device["lab_id"], device["device_id"],
                    "linux.ip-link-json", captured_at, encoded, digest, actor, created_at,
                ),
            )
            self._audit(connection, actor, observation_id, device, digest, captured_at)
        return {
            "observation_id": observation_id, "project_id": device["project_id"],
            "lab_id": device["lab_id"], "device_id": device["device_id"],
            "source": "linux.ip-link-json", "captured_at": captured_at,
            "payload_sha256": digest, "snapshot": payload,
        }

    @classmethod
    def _serialize(cls, row) -> dict[str, Any]:
        encoded = row["payload_json"]
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if digest != row["payload_sha256"]:
            raise DeviceObservationError("stored device observation failed its SHA-256 integrity check")
        try:
            payload = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise DeviceObservationError("stored device observation is not valid JSON") from exc
        return {
            "observation_id": row["observation_id"], "project_id": row["project_id"],
            "lab_id": row["lab_id"], "device_id": row["device_id"],
            "source": row["source"], "captured_at": row["captured_at"],
            "payload_sha256": digest, "observed_by": row["observed_by"],
            "snapshot": payload,
        }

    def list_for_device(self, device_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        if not isinstance(device_id, str) or not device_id.strip():
            raise DeviceObservationError("device_id must not be empty")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise DeviceObservationError("limit must be an integer")
        limit = max(1, min(limit, 100))
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM device_observation_snapshots
                   WHERE device_id=? ORDER BY captured_at DESC,observation_id DESC LIMIT ?""",
                (device_id, limit),
            ).fetchall()
        return [self._serialize(row) for row in rows]
