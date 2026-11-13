"""Typed, versioned Project configuration schema registry.

The registry intentionally supports a bounded JSON-Schema subset. It does
not execute caller-provided code, resolve remote references or permit secret
fields in network configuration.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import secrets
from typing import Any, Mapping


class ConfigurationSchemaError(ValueError):
    """Invalid schema definition or configuration values."""


class ConfigurationSchemaNotFound(LookupError):
    """Requested schema definition does not exist."""


_SENSITIVE_PROPERTY = re.compile(r"(?:password|passwd|secret|token|private.?key|api.?key|psk)", re.I)
_ALLOWED_SCHEMA_KEYS = frozenset({
    "type", "properties", "required", "additionalProperties", "enum",
    "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "items",
})
_ALLOWED_TYPES = frozenset({"object", "string", "integer", "number", "boolean", "array"})


def _json_copy(value: Any, path: str = "schema") -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ConfigurationSchemaError(f"{path} must contain JSON-compatible values") from exc


class ConfigurationSchemaRegistry:
    def __init__(self, database) -> None:
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _validate_schema_node(cls, node: object, path: str) -> dict:
        if not isinstance(node, Mapping):
            raise ConfigurationSchemaError(f"{path} must be a schema object")
        unknown = set(node) - _ALLOWED_SCHEMA_KEYS
        if unknown:
            raise ConfigurationSchemaError(f"{path} contains unsupported schema keyword(s): {', '.join(sorted(unknown))}")
        kind = node.get("type")
        if kind not in _ALLOWED_TYPES:
            raise ConfigurationSchemaError(f"{path}.type must be one of the supported JSON types")
        normalized = dict(node)
        if "enum" in node:
            enum_values = node["enum"]
            if not isinstance(enum_values, list) or not enum_values:
                raise ConfigurationSchemaError(f"{path}.enum must be a non-empty array")
            normalized["enum"] = _json_copy(enum_values, path + ".enum")
        if kind == "object":
            properties = node.get("properties", {})
            required = node.get("required", [])
            if not isinstance(properties, Mapping):
                raise ConfigurationSchemaError(f"{path}.properties must be an object")
            if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
                raise ConfigurationSchemaError(f"{path}.required must be an array of property names")
            if not set(required).issubset(set(properties)):
                raise ConfigurationSchemaError(f"{path}.required contains an unknown property")
            normalized_properties = {}
            for name, child in properties.items():
                if not isinstance(name, str) or not name or _SENSITIVE_PROPERTY.search(name):
                    raise ConfigurationSchemaError(f"{path} contains a sensitive or invalid property name")
                normalized_properties[name] = cls._validate_schema_node(child, path + "." + name)
            if node.get("additionalProperties", False) is not False:
                raise ConfigurationSchemaError(f"{path}.additionalProperties must be false")
            normalized["properties"] = normalized_properties
            normalized["required"] = list(required)
            normalized["additionalProperties"] = False
        elif kind == "array":
            if "items" not in node:
                raise ConfigurationSchemaError(f"{path}.items is required for arrays")
            normalized["items"] = cls._validate_schema_node(node["items"], path + "[]")
            for key in ("minItems", "maxItems"):
                if key in node and (isinstance(node[key], bool) or not isinstance(node[key], int) or node[key] < 0):
                    raise ConfigurationSchemaError(f"{path}.{key} must be a non-negative integer")
        elif kind == "string":
            for key in ("minLength", "maxLength"):
                if key in node and (isinstance(node[key], bool) or not isinstance(node[key], int) or node[key] < 0):
                    raise ConfigurationSchemaError(f"{path}.{key} must be a non-negative integer")
        elif kind in {"integer", "number"}:
            for key in ("minimum", "maximum"):
                if key in node and (isinstance(node[key], bool) or not isinstance(node[key], (int, float))):
                    raise ConfigurationSchemaError(f"{path}.{key} must be numeric")
            if "minimum" in node and "maximum" in node and node["minimum"] > node["maximum"]:
                raise ConfigurationSchemaError(f"{path}.minimum cannot exceed maximum")
        return _json_copy(normalized, path)

    @classmethod
    def normalize_definition(cls, definition: object) -> dict:
        return cls._validate_schema_node(definition, "schema")

    @staticmethod
    def _validate_value(value: object, schema: Mapping[str, Any], path: str, errors: list[dict]) -> None:
        kind = schema["type"]
        valid = (
            (kind == "object" and isinstance(value, dict))
            or (kind == "array" and isinstance(value, list))
            or (kind == "string" and isinstance(value, str))
            or (kind == "integer" and isinstance(value, int) and not isinstance(value, bool))
            or (kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
            or (kind == "boolean" and isinstance(value, bool))
        )
        if not valid:
            errors.append({"path": path, "message": f"expected {kind}"})
            return
        if "enum" in schema and value not in schema["enum"]:
            errors.append({"path": path, "message": "value is not in the allowed enumeration"})
        if kind in {"integer", "number"}:
            if "minimum" in schema and value < schema["minimum"]:
                errors.append({"path": path, "message": "value is below minimum"})
            if "maximum" in schema and value > schema["maximum"]:
                errors.append({"path": path, "message": "value exceeds maximum"})
        if kind == "string":
            if "minLength" in schema and len(value) < schema["minLength"]:
                errors.append({"path": path, "message": "string is shorter than minimum length"})
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                errors.append({"path": path, "message": "string exceeds maximum length"})
        if kind == "array":
            if "minItems" in schema and len(value) < schema["minItems"]:
                errors.append({"path": path, "message": "array contains too few items"})
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                errors.append({"path": path, "message": "array contains too many items"})
            for index, item in enumerate(value):
                ConfigurationSchemaRegistry._validate_value(item, schema["items"], f"{path}[{index}]", errors)
        if kind == "object":
            properties = schema["properties"]
            for required in schema["required"]:
                if required not in value:
                    errors.append({"path": path + "." + required, "message": "required property is missing"})
            for name, child in value.items():
                if not isinstance(name, str) or name not in properties:
                    errors.append({"path": path + "." + str(name)[:80], "message": "property is not defined by the schema"})
                    continue
                ConfigurationSchemaRegistry._validate_value(child, properties[name], path + "." + name, errors)

    def register(
        self, *, project_id: str, schema_id: str, version: int, name: str,
        definition: Mapping[str, Any], actor: str,
    ) -> dict:
        project_id = str(project_id or "").strip()
        schema_id = str(schema_id or "").strip()
        name = str(name or "").strip()
        actor = str(actor or "").strip()
        if not project_id or len(project_id) > 128:
            raise ConfigurationSchemaError("project_id is required")
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,127}", schema_id):
            raise ConfigurationSchemaError("schema_id must be a stable lowercase identifier")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ConfigurationSchemaError("schema version must be a positive integer")
        if not name or len(name) > 120:
            raise ConfigurationSchemaError("schema name must contain 1 to 120 characters")
        if not actor or len(actor) > 128:
            raise ConfigurationSchemaError("actor is required")
        normalized = self.normalize_definition(definition)
        record_id = secrets.token_hex(16)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            latest = connection.execute(
                "SELECT MAX(version) FROM configuration_schemas WHERE project_id=? AND schema_id=?",
                (project_id, schema_id),
            ).fetchone()[0]
            expected = int(latest or 0) + 1
            if version != expected:
                raise ConfigurationSchemaError(f"schema version must be the next version ({expected})")
            connection.execute(
                """INSERT INTO configuration_schemas(
                    schema_record_id,project_id,schema_id,version,name,definition_json,status,created_at,created_by
                ) VALUES(?,?,?,?,?,?,'ACTIVE',?,?)""",
                (record_id, project_id, schema_id, version, name,
                 json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                 now, actor),
            )
            connection.execute(
                """INSERT INTO audit_events(
                    audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
                ) VALUES(?,?,?,?,?,?,?)""",
                ("AUD-" + secrets.token_hex(12), actor, "CONFIGURATION_SCHEMA_REGISTERED",
                 "CONFIGURATION_SCHEMA", record_id,
                 json.dumps({"project_id": project_id, "schema_id": schema_id, "version": version}, sort_keys=True),
                 now),
            )
        return {
            "schema_record_id": record_id, "project_id": project_id, "schema_id": schema_id,
            "version": version, "name": name, "definition": normalized, "status": "ACTIVE",
            "created_at": now, "created_by": actor,
        }

    def list(self, project_id: str) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT schema_record_id,project_id,schema_id,version,name,definition_json,
                          status,created_at,created_by
                   FROM configuration_schemas WHERE project_id=?
                   ORDER BY schema_id,version DESC""",
                (project_id,),
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def get(self, project_id: str, schema_id: str, version: int | None = None) -> dict | None:
        with self.database.connection() as connection:
            if version is None:
                row = connection.execute(
                    """SELECT * FROM configuration_schemas
                       WHERE project_id=? AND schema_id=? AND status='ACTIVE'
                       ORDER BY version DESC LIMIT 1""",
                    (project_id, schema_id),
                ).fetchone()
            else:
                row = connection.execute(
                    """SELECT * FROM configuration_schemas
                       WHERE project_id=? AND schema_id=? AND version=?""",
                    (project_id, schema_id, version),
                ).fetchone()
        return self._serialize(row) if row is not None else None

    @staticmethod
    def _serialize(row) -> dict:
        return {
            "schema_record_id": row["schema_record_id"], "project_id": row["project_id"],
            "schema_id": row["schema_id"], "version": row["version"], "name": row["name"],
            "definition": json.loads(row["definition_json"]), "status": row["status"],
            "created_at": row["created_at"], "created_by": row["created_by"],
        }

    def validate(self, project_id: str, schema_id: str, version: int, values: object) -> dict:
        schema = self.get(project_id, schema_id, version)
        if schema is None:
            raise ConfigurationSchemaNotFound("configuration schema not found")
        if not isinstance(values, dict):
            raise ConfigurationSchemaError("configuration values must be an object")
        normalized = _json_copy(values, "configuration values")
        errors: list[dict] = []
        self._validate_value(normalized, schema["definition"], "$", errors)
        return {"valid": not errors, "errors": errors, "values": normalized}
