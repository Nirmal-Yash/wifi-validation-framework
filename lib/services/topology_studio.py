"""Canonical, Project/Lab-scoped topology profiles and immutable revisions."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, math, re, secrets
from typing import Any, Mapping


class TopologyStudioError(ValueError):
    """Invalid topology definition or lifecycle transition."""


class TopologyStudioNotFound(LookupError):
    """Topology profile, revision or parent scope was not found."""


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_TEMPLATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_NODE_TYPES = frozenset({"ROUTER", "SWITCH", "ACCESS_POINT", "CLIENT", "MONITOR", "CLOUD", "OTHER"})
_SECRET_PARTS = ("password", "passwd", "secret", "token", "private_key", "api_key", "psk", "credential")


class TopologyStudioService:
    MAX_NODES = 128
    MAX_LINKS = 512
    MAX_COORDINATE = 10000

    def __init__(self, database) -> None:
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise TopologyStudioError("actor must contain 1 to 128 printable characters")
        return actor

    @staticmethod
    def _text(value: object, name: str, maximum: int, *, required: bool = True) -> str:
        if value is None and not required:
            return ""
        if not isinstance(value, str):
            raise TopologyStudioError(f"{name} must be a string")
        result = value.strip()
        if (required and not result) or len(result) > maximum or any(ord(char) < 32 for char in result):
            raise TopologyStudioError(f"{name} must contain 1 to {maximum} printable characters")
        return result

    @classmethod
    def normalize_definition(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != {"nodes", "links"}:
            raise TopologyStudioError("topology definition must contain only nodes and links arrays")
        raw_nodes, raw_links = value.get("nodes"), value.get("links")
        if not isinstance(raw_nodes, list) or not isinstance(raw_links, list):
            raise TopologyStudioError("nodes and links must be arrays")
        if len(raw_nodes) > cls.MAX_NODES or len(raw_links) > cls.MAX_LINKS:
            raise TopologyStudioError(f"topology limits are {cls.MAX_NODES} nodes and {cls.MAX_LINKS} links")
        nodes: list[dict[str, Any]] = []
        node_ids: set[str] = set()
        for index, raw in enumerate(raw_nodes):
            prefix = f"nodes[{index}]"
            if not isinstance(raw, Mapping):
                raise TopologyStudioError(f"{prefix} must be an object")
            if set(raw) - {"id", "name", "node_type", "template_id", "x", "y", "properties"}:
                raise TopologyStudioError(f"{prefix} contains unsupported properties")
            node_id = cls._text(raw.get("id"), f"{prefix}.id", 64)
            if not _ID.fullmatch(node_id) or node_id in node_ids:
                raise TopologyStudioError(f"{prefix}.id is invalid or duplicated")
            node_ids.add(node_id)
            name = cls._text(raw.get("name"), f"{prefix}.name", 120)
            node_type = cls._text(raw.get("node_type"), f"{prefix}.node_type", 24).upper()
            if node_type not in _NODE_TYPES:
                raise TopologyStudioError(f"{prefix}.node_type is not supported")
            template_id = cls._text(raw.get("template_id"), f"{prefix}.template_id", 128)
            if not _TEMPLATE_ID.fullmatch(template_id):
                raise TopologyStudioError(f"{prefix}.template_id contains unsupported characters")
            coords: dict[str, float] = {}
            for axis in ("x", "y"):
                number = raw.get(axis)
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(float(number)):
                    raise TopologyStudioError(f"{prefix}.{axis} must be a finite coordinate")
                if number < 0 or number > cls.MAX_COORDINATE:
                    raise TopologyStudioError(f"{prefix}.{axis} must be between 0 and {cls.MAX_COORDINATE}")
                coords[axis] = round(float(number), 3)
            properties = raw.get("properties", {})
            if properties is None:
                properties = {}
            if not isinstance(properties, Mapping) or len(properties) > 32:
                raise TopologyStudioError(f"{prefix}.properties must be a bounded object")
            safe_properties: dict[str, Any] = {}
            for key, item in properties.items():
                property_name = cls._text(key, f"{prefix}.properties key", 64)
                if any(part in property_name.lower() for part in _SECRET_PARTS):
                    raise TopologyStudioError("topology properties cannot contain credential-like names")
                if isinstance(item, float) and not math.isfinite(item):
                    raise TopologyStudioError(f"{prefix}.properties values must be finite scalar values")
                if not isinstance(item, (str, int, float, bool)):
                    raise TopologyStudioError(f"{prefix}.properties values must be finite scalar values")
                if isinstance(item, str) and (len(item) > 256 or any(ord(ch) < 32 for ch in item)):
                    raise TopologyStudioError(f"{prefix}.properties.{property_name} is too long or contains control characters")
                safe_properties[property_name] = item
            nodes.append({
                "id": node_id, "name": name, "node_type": node_type, "template_id": template_id,
                "x": coords["x"], "y": coords["y"], "properties": safe_properties,
            })
        occupied: set[tuple[str, int, int]] = set()
        link_ids: set[str] = set()
        links: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_links):
            prefix = f"links[{index}]"
            if not isinstance(raw, Mapping):
                raise TopologyStudioError(f"{prefix} must be an object")
            allowed = {"id", "source_node_id", "source_adapter", "source_port", "target_node_id", "target_adapter", "target_port"}
            if set(raw) != allowed:
                raise TopologyStudioError(f"{prefix} must contain exactly the declared endpoint fields")
            link_id = cls._text(raw.get("id"), f"{prefix}.id", 64)
            if not _ID.fullmatch(link_id) or link_id in link_ids:
                raise TopologyStudioError(f"{prefix}.id is invalid or duplicated")
            link_ids.add(link_id)
            source = cls._text(raw.get("source_node_id"), f"{prefix}.source_node_id", 64)
            target = cls._text(raw.get("target_node_id"), f"{prefix}.target_node_id", 64)
            if source not in node_ids or target not in node_ids:
                raise TopologyStudioError(f"{prefix} references an unknown logical node")
            if source == target:
                raise TopologyStudioError(f"{prefix} cannot connect a node to itself")
            endpoint_values: dict[str, int] = {}
            for field in ("source_adapter", "source_port", "target_adapter", "target_port"):
                number = raw.get(field)
                if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 255:
                    raise TopologyStudioError(f"{prefix}.{field} must be an integer from 0 to 255")
                endpoint_values[field] = number
            endpoints = (
                (source, endpoint_values["source_adapter"], endpoint_values["source_port"]),
                (target, endpoint_values["target_adapter"], endpoint_values["target_port"]),
            )
            if endpoints[0] in occupied or endpoints[1] in occupied:
                raise TopologyStudioError(f"{prefix} reuses an occupied adapter/port")
            occupied.update(endpoints)
            links.append({
                "id": link_id, "source_node_id": source,
                "source_adapter": endpoint_values["source_adapter"], "source_port": endpoint_values["source_port"],
                "target_node_id": target, "target_adapter": endpoint_values["target_adapter"],
                "target_port": endpoint_values["target_port"],
            })
        nodes.sort(key=lambda item: item["id"])
        links.sort(key=lambda item: item["id"])
        return {"nodes": nodes, "links": links}

    @classmethod
    def canonical_payload(cls, definition: object) -> tuple[dict[str, Any], str, str]:
        normalized = cls.normalize_definition(definition)
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return normalized, encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _profile(row) -> dict | None:
        if row is None:
            return None
        return {key: row[key] for key in ("profile_id", "project_id", "name", "description", "scope_type", "scope_id",
                                          "lab_id", "status", "created_at", "updated_at", "created_by", "updated_by")}

    @staticmethod
    def _revision(row) -> dict | None:
        if row is None:
            return None
        return {key: row[key] for key in ("revision_id", "profile_id", "revision_number", "content_sha256", "status",
                                          "created_at", "created_by", "published_at", "published_by")} | {
            "definition": json.loads(row["definition_json"])
        }

    @staticmethod
    def _audit(connection, actor, action, resource_type, resource_id, details):
        connection.execute(
            """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("AUD-" + secrets.token_hex(12), actor, action, resource_type, resource_id,
             json.dumps(details, sort_keys=True, separators=(",", ":")), TopologyStudioService._now()),
        )

    def get_profile(self, profile_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM topology_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        return self._profile(row)

    def list_profiles(self, project_id: str) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute("SELECT * FROM topology_profiles WHERE project_id=? ORDER BY scope_type,scope_id,name",
                                      (project_id,)).fetchall()
        return [self._profile(row) for row in rows]

    def create_profile(self, *, project_id: str, name: str, description: str = "",
                       scope_type: str = "PROJECT", scope_id: str | None = None, actor: str) -> dict:
        project_id = self._text(project_id, "project_id", 128)
        name = self._text(name, "name", 120)
        description = self._text(description or "", "description", 500, required=False)
        scope_type = str(scope_type or "PROJECT").strip().upper()
        actor = self._actor(actor)
        if scope_type not in {"PROJECT", "LAB"}:
            raise TopologyStudioError("scope_type must be PROJECT or LAB")
        lab_id = None
        if scope_type == "PROJECT":
            scope_id = project_id
        else:
            scope_id = self._text(scope_id, "scope_id", 128)
            lab_id = scope_id
            with self.database.connection() as connection:
                lab = connection.execute("SELECT project_id,status FROM labs WHERE lab_id=?", (lab_id,)).fetchone()
            if lab is None or lab["project_id"] != project_id:
                raise TopologyStudioNotFound("Lab not found in this Project")
            if lab["status"] != "ACTIVE":
                raise TopologyStudioError("topology profiles require an active Lab scope")
        now = self._now()
        profile_id = "top_" + secrets.token_hex(12)
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO topology_profiles(profile_id,project_id,name,description,scope_type,scope_id,lab_id,status,
                       created_at,updated_at,created_by,updated_by)
                       VALUES(?,?,?,?,?,?,?,'ACTIVE',?,?,?,?)""",
                    (profile_id, project_id, name, description or "", scope_type, scope_id, lab_id, now, now, actor, actor),
                )
                self._audit(connection, actor, "TOPOLOGY_PROFILE_CREATED", "TOPOLOGY_PROFILE", profile_id,
                            {"project_id": project_id, "scope_type": scope_type, "scope_id": scope_id})
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise TopologyStudioError("a topology profile with this name already exists at this scope") from exc
            if "FOREIGN KEY constraint failed" in str(exc):
                raise TopologyStudioNotFound("Project or Lab no longer exists") from exc
            raise
        return self.get_profile(profile_id) or {}

    def list_revisions(self, profile_id: str) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute("SELECT * FROM topology_revisions WHERE profile_id=? ORDER BY revision_number DESC",
                                      (profile_id,)).fetchall()
        return [self._revision(row) for row in rows]

    def get_revision(self, revision_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM topology_revisions WHERE revision_id=?", (revision_id,)).fetchone()
        return self._revision(row)

    def create_revision(self, profile_id: str, *, definition: object, actor: str) -> dict:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise TopologyStudioNotFound("topology profile not found")
        if profile["status"] != "ACTIVE":
            raise TopologyStudioError("archived topology profiles cannot receive revisions")
        actor = self._actor(actor)
        normalized, encoded, digest = self.canonical_payload(definition)
        revision_id = "tpr_" + secrets.token_hex(12)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            number = int(connection.execute("SELECT COALESCE(MAX(revision_number),0)+1 FROM topology_revisions WHERE profile_id=?",
                                             (profile_id,)).fetchone()[0])
            connection.execute(
                """INSERT INTO topology_revisions(revision_id,profile_id,revision_number,definition_json,content_sha256,status,
                   created_at,created_by,published_at,published_by) VALUES(?,?,?,?,?,'DRAFT',?,?,NULL,NULL)""",
                (revision_id, profile_id, number, encoded, digest, now, actor),
            )
            self._audit(connection, actor, "TOPOLOGY_REVISION_CREATED", "TOPOLOGY_REVISION", revision_id,
                        {"profile_id": profile_id, "revision_number": number, "content_sha256": digest,
                         "node_count": len(normalized["nodes"]), "link_count": len(normalized["links"])})
        return self.get_revision(revision_id) or {}

    def publish(self, profile_id: str, revision_id: str, *, actor: str) -> dict:
        profile = self.get_profile(profile_id)
        revision = self.get_revision(revision_id)
        if profile is None or revision is None or revision["profile_id"] != profile_id:
            raise TopologyStudioNotFound("topology profile or revision not found")
        if revision["status"] != "DRAFT":
            raise TopologyStudioError("only draft topology revisions can be published")
        actor = self._actor(actor)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute("UPDATE topology_revisions SET status='PUBLISHED',published_at=?,published_by=? "
                                        "WHERE revision_id=? AND status='DRAFT'", (now, actor, revision_id))
            if cursor.rowcount != 1:
                raise TopologyStudioError("topology revision changed during publish")
            self._audit(connection, actor, "TOPOLOGY_REVISION_PUBLISHED", "TOPOLOGY_REVISION", revision_id,
                        {"profile_id": profile_id, "content_sha256": revision["content_sha256"]})
        return self.get_revision(revision_id) or {}
