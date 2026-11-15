"""Project/Lab-scoped device inventory with credential references only."""
from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import json
import re
import secrets
from typing import Any, Mapping

from lib.adapters.device import DeviceCapabilities
from lib.repositories import SQLiteDatabase


class DeviceInventoryError(ValueError):
    """Invalid device inventory record or lifecycle transition."""


class DeviceInventoryNotFound(LookupError):
    """Device or parent resource is missing from the selected scope."""


_DEVICE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_DEVICE_TYPES = frozenset({"ROUTER", "ACCESS_POINT", "CLIENT", "MONITOR", "SWITCH", "SERVER", "OTHER"})
_SECRET_NAMES = ("password", "passwd", "secret", "token", "private_key", "api_key", "psk", "credential")


class DeviceInventoryService:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise DeviceInventoryError("actor must contain 1 to 128 printable characters")
        return actor

    @staticmethod
    def _text(value: object, field: str, *, required: bool, maximum: int) -> str | None:
        if value is None and not required:
            return None
        if not isinstance(value, str):
            raise DeviceInventoryError(f"{field} must be a string")
        result = value.strip()
        if (required and not result) or len(result) > maximum or any(ord(char) < 32 for char in result):
            raise DeviceInventoryError(f"{field} must contain 1 to {maximum} printable characters")
        return result or None

    @staticmethod
    def _host(value: object) -> str:
        host = DeviceInventoryService._text(value, "host", required=True, maximum=253)
        candidate = host.strip("[]")
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            labels = candidate.rstrip(".").split(".")
            if not labels or any(not _DNS_LABEL.fullmatch(label) for label in labels):
                raise DeviceInventoryError("host must be an IP address or valid DNS hostname")
            return candidate.rstrip(".").lower()

    @staticmethod
    def _metadata(value: object) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise DeviceInventoryError("metadata must be a JSON object")
        def validate(node, depth=0):
            if depth > 6:
                raise DeviceInventoryError("metadata nesting exceeds the supported depth")
            if isinstance(node, Mapping):
                result = {}
                for key, child in node.items():
                    name = str(key)
                    if not name or len(name) > 64 or any(token in name.lower() for token in _SECRET_NAMES):
                        raise DeviceInventoryError("metadata cannot contain credential-like property names")
                    result[name] = validate(child, depth + 1)
                return result
            if isinstance(node, (list, tuple)):
                if len(node) > 100:
                    raise DeviceInventoryError("metadata arrays are limited to 100 entries")
                return [validate(child, depth + 1) for child in node]
            if node is None or isinstance(node, (str, bool, int)):
                return node
            if isinstance(node, float):
                import math
                if not math.isfinite(node):
                    raise DeviceInventoryError("metadata numbers must be finite")
                return node
            raise DeviceInventoryError("metadata contains an unsupported value")
        result = validate(value)
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 16384:
            raise DeviceInventoryError("metadata exceeds 16 KiB")
        return result

    @staticmethod
    def _capabilities(value: object) -> dict[str, bool]:
        if value is None:
            return DeviceCapabilities().as_dict()
        if not isinstance(value, Mapping):
            raise DeviceInventoryError("capabilities must be an object of boolean values")
        supported = DeviceCapabilities.__dataclass_fields__
        unknown = set(value) - set(supported)
        if unknown:
            raise DeviceInventoryError("unknown device capability: " + sorted(unknown)[0])
        defaults = DeviceCapabilities().as_dict()
        for key, enabled in value.items():
            if not isinstance(enabled, bool):
                raise DeviceInventoryError(f"capabilities.{key} must be boolean")
            defaults[key] = enabled
        return defaults

    @classmethod
    def _normalize(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        project_id = cls._text(payload.get("project_id"), "project_id", required=True, maximum=128)
        lab_id = cls._text(payload.get("lab_id"), "lab_id", required=True, maximum=128)
        device_key = cls._text(payload.get("device_key"), "device_key", required=True, maximum=64)
        if not _DEVICE_KEY.fullmatch(device_key):
            raise DeviceInventoryError("device_key must use letters, numbers, dot, underscore or hyphen")
        name = cls._text(payload.get("name"), "name", required=True, maximum=120)
        device_type = str(payload.get("device_type", "")).strip().upper()
        if device_type not in _DEVICE_TYPES:
            raise DeviceInventoryError("device_type is not supported")
        port = payload.get("port", 22)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise DeviceInventoryError("port must be an integer from 1 to 65535")
        status = str(payload.get("status", "ACTIVE")).strip().upper()
        if status not in {"ACTIVE", "ARCHIVED"}:
            raise DeviceInventoryError("status must be ACTIVE or ARCHIVED")
        return {
            "project_id": project_id, "lab_id": lab_id, "device_key": device_key,
            "name": name, "device_type": device_type,
            "host": cls._host(payload.get("host")), "port": port,
            "vendor": cls._text(payload.get("vendor"), "vendor", required=False, maximum=80),
            "model": cls._text(payload.get("model"), "model", required=False, maximum=120),
            "username": cls._text(payload.get("username"), "username", required=False, maximum=128),
            "credential_id": cls._text(payload.get("credential_id"), "credential_id", required=False, maximum=128),
            "capabilities": cls._capabilities(payload.get("capabilities")),
            "metadata": cls._metadata(payload.get("metadata")),
            "status": status,
        }

    @staticmethod
    def _serialize(row) -> dict[str, Any]:
        if row is None:
            return None
        return {
            "device_id": row["device_id"], "project_id": row["project_id"],
            "lab_id": row["lab_id"], "device_key": row["device_key"],
            "name": row["name"], "device_type": row["device_type"],
            "host": row["host"], "port": row["port"], "vendor": row["vendor"],
            "model": row["model"], "username": row["username"],
            "credential_id": row["credential_id"],
            "capabilities": json.loads(row["capabilities_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "status": row["status"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "created_by": row["created_by"],
            "updated_by": row["updated_by"],
        }

    @staticmethod
    def _audit(connection, actor: str, action: str, device_id: str, details: dict) -> None:
        connection.execute(
            """INSERT INTO audit_events(
               audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
               ) VALUES(?,?,?,?,?,?,?)""",
            ("AUD-" + secrets.token_hex(12), actor, action, "DEVICE", device_id,
             json.dumps(details, sort_keys=True, separators=(",", ":")), DeviceInventoryService._now()),
        )

    def get(self, device_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        return self._serialize(row)

    def list(self, project_id: str, *, lab_id: str | None = None, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM devices WHERE project_id=?"
        params: list[object] = [project_id]
        if lab_id:
            query += " AND lab_id=?"
            params.append(lab_id)
        if status:
            query += " AND status=?"
            params.append(str(status).upper())
        query += " ORDER BY name COLLATE NOCASE, device_key"
        with self.database.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._serialize(row) for row in rows]

    def _validate_parent_and_credential(self, item: dict[str, Any], device_id: str | None) -> None:
        with self.database.connection() as connection:
            lab = connection.execute(
                "SELECT project_id,status FROM labs WHERE lab_id=?", (item["lab_id"],)
            ).fetchone()
            if lab is None or lab["project_id"] != item["project_id"]:
                raise DeviceInventoryNotFound("Lab not found in this Project")
            if lab["status"] != "ACTIVE":
                raise DeviceInventoryError("devices can only be registered in an active Lab")
            project = connection.execute(
                "SELECT status FROM projects WHERE project_id=?", (item["project_id"],)
            ).fetchone()
            if project is None:
                raise DeviceInventoryNotFound("Project not found")
            if project["status"] != "ACTIVE":
                raise DeviceInventoryError("devices can only be registered in an active Project")
            credential_id = item.get("credential_id")
            if credential_id:
                credential = connection.execute(
                    """SELECT project_id,device_id,status FROM managed_credentials
                       WHERE credential_id=?""", (credential_id,)
                ).fetchone()
                if credential is None or credential["project_id"] != item["project_id"] or credential["device_id"] != device_id:
                    raise DeviceInventoryError("credential must belong to this Project and exact device")
                if credential["status"] != "ACTIVE":
                    raise DeviceInventoryError("revoked credentials cannot be linked to a device")

    def create(self, payload: Mapping[str, Any], *, actor: str) -> dict:
        if not isinstance(payload, Mapping):
            raise DeviceInventoryError("device payload must be an object")
        item = self._normalize(payload)
        if item["status"] != "ACTIVE":
            raise DeviceInventoryError("new devices must be created in ACTIVE status")
        actor = self._actor(actor)
        device_id = "dev_" + secrets.token_hex(12)
        self._validate_parent_and_credential(item, device_id)
        now = self._now()
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO devices(
                       device_id,project_id,lab_id,device_key,name,device_type,host,port,
                       vendor,model,username,credential_id,capabilities_json,metadata_json,
                       status,created_at,updated_at,created_by,updated_by)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (device_id,item["project_id"],item["lab_id"],item["device_key"],item["name"],
                     item["device_type"],item["host"],item["port"],item["vendor"],item["model"],
                     item["username"],item["credential_id"],
                     json.dumps(item["capabilities"],sort_keys=True,separators=(",",":")),
                     json.dumps(item["metadata"],sort_keys=True,separators=(",",":")),
                     item["status"],now,now,actor,actor),
                )
                self._audit(connection,actor,"DEVICE_CREATED",device_id,
                            {"project_id":item["project_id"],"lab_id":item["lab_id"],"device_key":item["device_key"]})
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise DeviceInventoryError("device_key already exists in this Lab") from exc
            if "FOREIGN KEY constraint failed" in str(exc):
                raise DeviceInventoryNotFound("Project, Lab or credential no longer exists") from exc
            raise
        return self.get(device_id)

    def update(self, device_id: str, payload: Mapping[str, Any], *, actor: str) -> dict:
        existing = self.get(device_id)
        if existing is None:
            raise DeviceInventoryNotFound("device not found")
        if existing["status"] == "ARCHIVED":
            raise DeviceInventoryError("archived devices cannot be modified")
        if not isinstance(payload, Mapping):
            raise DeviceInventoryError("device payload must be an object")
        merged = dict(existing)
        merged.update(payload)
        item = self._normalize(merged)
        if item["project_id"] != existing["project_id"] or item["lab_id"] != existing["lab_id"]:
            raise DeviceInventoryError("device ownership and Lab cannot be changed after creation")
        actor = self._actor(actor)
        self._validate_parent_and_credential(item, device_id)
        now = self._now()
        try:
            with self.database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    """UPDATE devices SET device_key=?,name=?,device_type=?,host=?,port=?,vendor=?,
                       model=?,username=?,credential_id=?,capabilities_json=?,metadata_json=?,
                       status=?,updated_at=?,updated_by=? WHERE device_id=? AND status='ACTIVE'""",
                    (item["device_key"],item["name"],item["device_type"],item["host"],item["port"],
                     item["vendor"],item["model"],item["username"],item["credential_id"],
                     json.dumps(item["capabilities"],sort_keys=True,separators=(",",":")),
                     json.dumps(item["metadata"],sort_keys=True,separators=(",",":")),
                     item["status"],now,actor,device_id),
                )
                if cursor.rowcount != 1:
                    raise DeviceInventoryError("device changed during update")
                self._audit(connection,actor,"DEVICE_UPDATED",device_id,
                            {"project_id":item["project_id"],"lab_id":item["lab_id"],"status":item["status"]})
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise DeviceInventoryError("device_key already exists in this Lab") from exc
            raise
        return self.get(device_id)
