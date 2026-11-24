"""Generic immutable native topology source and asset provenance."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from lib.services.topology_metadata import (
    MetadataValidationError,
    bounded_json_value,
    canonical_json,
    safe_relative_path,
    sha256_bytes,
)


class TopologySourceArtifactError(ValueError):
    """Invalid native topology source or asset provenance."""


class TopologySourceArtifactNotFound(LookupError):
    """Native topology source artifact or asset was not found."""


class TopologySourceArtifactService:
    MAX_SOURCE_BYTES = 50 * 1024 * 1024
    MAX_ASSET_BYTES = 20 * 1024 * 1024
    MAX_ASSET_TOTAL_BYTES = 100 * 1024 * 1024
    MAX_ASSETS = 100
    MAX_METADATA_BYTES = 500_000

    def __init__(self, database) -> None:
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise TopologySourceArtifactError("actor must contain 1 to 128 printable characters")
        return actor

    @staticmethod
    def _filename(value: object) -> str:
        if not isinstance(value, str):
            raise TopologySourceArtifactError("filename must be a string")
        name = value.strip()
        if (
            not name or len(name) > 255 or name in {".", ".."}
            or "/" in name or "\\" in name or any(ord(char) < 32 for char in name)
        ):
            raise TopologySourceArtifactError("filename must be a safe basename of at most 255 characters")
        return name

    @staticmethod
    def _bytes(value: object, name: str, maximum: int) -> bytes:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TopologySourceArtifactError(f"{name} must be bytes")
        result = bytes(value)
        if not result or len(result) > maximum:
            raise TopologySourceArtifactError(f"{name} must contain between 1 and {maximum} bytes")
        return result

    @staticmethod
    def _metadata(value: object) -> tuple[dict[str, Any], str]:
        if value is None:
            value = {}
        if not isinstance(value, Mapping):
            raise TopologySourceArtifactError("metadata must be an object")
        try:
            normalized = bounded_json_value(
                value, maximum_bytes=TopologySourceArtifactService.MAX_METADATA_BYTES,
                maximum_depth=8, maximum_items=4096, maximum_string=8192,
            )
            encoded, _ = canonical_json(
                normalized, maximum_bytes=TopologySourceArtifactService.MAX_METADATA_BYTES,
            )
        except MetadataValidationError as exc:
            raise TopologySourceArtifactError(str(exc)) from exc
        return normalized, encoded

    def record_source_artifact(
        self,
        profile_id: str,
        topology_revision_id: str,
        *,
        source_bytes: bytes,
        format_id: str,
        format_version: str,
        filename: str,
        codec_name: str,
        codec_version: str,
        metadata: Mapping[str, Any] | None = None,
        assets: Sequence[Mapping[str, Any]] = (),
        actor: str,
    ) -> dict:
        actor = self._actor(actor)
        if not isinstance(format_id, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", format_id):
            raise TopologySourceArtifactError("format_id must be an uppercase native-format identifier")
        if not isinstance(format_version, str) or not 1 <= len(format_version.strip()) <= 32 or any(ord(ch) < 32 for ch in format_version):
            raise TopologySourceArtifactError("format_version must contain 1 to 32 characters")
        if not isinstance(codec_name, str) or not 1 <= len(codec_name.strip()) <= 64 or any(ord(ch) < 32 for ch in codec_name):
            raise TopologySourceArtifactError("codec_name must contain 1 to 64 characters")
        if not isinstance(codec_version, str) or not 1 <= len(codec_version.strip()) <= 64 or any(ord(ch) < 32 for ch in codec_version):
            raise TopologySourceArtifactError("codec_version must contain 1 to 64 characters")
        source = self._bytes(source_bytes, "source_bytes", self.MAX_SOURCE_BYTES)
        clean_filename = self._filename(filename)
        normalized_metadata, metadata_json = self._metadata(metadata)
        if assets is None:
            assets = ()
        if not isinstance(assets, (list, tuple)) or len(assets) > self.MAX_ASSETS:
            raise TopologySourceArtifactError(f"assets must be an array of at most {self.MAX_ASSETS} entries")
        normalized_assets: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        total_asset_bytes = 0
        for index, raw in enumerate(assets):
            if not isinstance(raw, Mapping) or set(raw) - {"relative_path", "media_type", "content_bytes"}:
                raise TopologySourceArtifactError(f"assets[{index}] contains unsupported fields")
            try:
                path = safe_relative_path(raw.get("relative_path"), field_name=f"assets[{index}].relative_path")
            except MetadataValidationError as exc:
                raise TopologySourceArtifactError(str(exc)) from exc
            if path in seen_paths:
                raise TopologySourceArtifactError(f"assets[{index}].relative_path is duplicated")
            seen_paths.add(path)
            content = self._bytes(raw.get("content_bytes"), f"assets[{index}].content_bytes", self.MAX_ASSET_BYTES)
            total_asset_bytes += len(content)
            if total_asset_bytes > self.MAX_ASSET_TOTAL_BYTES:
                raise TopologySourceArtifactError("combined source asset bytes exceed the 100 MiB limit")
            media_type = raw.get("media_type")
            if media_type not in (None, "") and (
                not isinstance(media_type, str) or len(media_type.strip()) > 128
                or any(ord(char) < 32 for char in media_type)
            ):
                raise TopologySourceArtifactError(f"assets[{index}].media_type is invalid")
            normalized_assets.append({
                "asset_id": "tsa_" + secrets.token_hex(12),
                "relative_path": path,
                "media_type": media_type.strip() if isinstance(media_type, str) else "",
                "content_bytes": content,
                "sha256": sha256_bytes(content),
                "size_bytes": len(content),
            })

        source_id = "tsr_" + secrets.token_hex(12)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            base = connection.execute(
                """SELECT p.project_id,p.profile_id,p.status AS profile_status,
                          r.content_sha256,r.revision_id
                   FROM topology_profiles p JOIN topology_revisions r ON r.profile_id=p.profile_id
                   WHERE p.profile_id=? AND r.revision_id=?""",
                (profile_id, topology_revision_id),
            ).fetchone()
            if base is None:
                raise TopologySourceArtifactNotFound("topology profile or revision not found")
            if base["profile_status"] != "ACTIVE":
                raise TopologySourceArtifactError("archived topology profiles cannot receive source artifacts")
            connection.execute(
                """INSERT INTO topology_source_artifacts(
                    source_id,project_id,profile_id,topology_revision_id,topology_content_sha256,
                    format_id,format_version,filename,sha256,size_bytes,source_bytes,codec_name,
                    codec_version,metadata_json,imported_at,imported_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    source_id, base["project_id"], profile_id, topology_revision_id, base["content_sha256"],
                    format_id, format_version.strip(), clean_filename, sha256_bytes(source), len(source),
                    source, codec_name.strip(), codec_version.strip(), metadata_json, now, actor,
                ),
            )
            for asset in normalized_assets:
                connection.execute(
                    """INSERT INTO topology_source_assets(
                        asset_id,source_id,relative_path,media_type,sha256,size_bytes,content_bytes,created_at
                    ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        asset["asset_id"], source_id, asset["relative_path"], asset["media_type"],
                        asset["sha256"], asset["size_bytes"], asset["content_bytes"], now,
                    ),
                )
            connection.execute(
                """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    "AUD-" + secrets.token_hex(12), actor, "TOPOLOGY_NATIVE_SOURCE_RECORDED",
                    "TOPOLOGY_SOURCE_ARTIFACT", source_id,
                    json.dumps({
                        "project_id": base["project_id"], "profile_id": profile_id,
                        "topology_revision_id": topology_revision_id, "format_id": format_id,
                        "format_version": format_version.strip(), "filename": clean_filename,
                        "sha256": sha256_bytes(source), "size_bytes": len(source),
                        "asset_count": len(normalized_assets), "asset_bytes": total_asset_bytes,
                    }, sort_keys=True, separators=(",", ":")),
                    now,
                ),
            )
        return self.get_source_artifact(source_id) or {}

    @staticmethod
    def _row(row, *, asset_count: int = 0) -> dict | None:
        if row is None:
            return None
        return {
            "source_id": row["source_id"],
            "project_id": row["project_id"],
            "profile_id": row["profile_id"],
            "topology_revision_id": row["topology_revision_id"],
            "topology_content_sha256": row["topology_content_sha256"],
            "format_id": row["format_id"],
            "format_version": row["format_version"],
            "filename": row["filename"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "codec_name": row["codec_name"],
            "codec_version": row["codec_version"],
            "metadata": json.loads(row["metadata_json"]),
            "asset_count": asset_count,
            "imported_at": row["imported_at"],
            "imported_by": row["imported_by"],
        }

    def list_source_artifacts(self, profile_id: str) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT s.*,COUNT(a.asset_id) AS asset_count
                   FROM topology_source_artifacts s
                   LEFT JOIN topology_source_assets a ON a.source_id=s.source_id
                   WHERE s.profile_id=?
                   GROUP BY s.source_id
                   ORDER BY s.imported_at DESC,s.source_id""",
                (profile_id,),
            ).fetchall()
        return [self._row(row, asset_count=int(row["asset_count"])) for row in rows]

    def get_source_artifact(self, source_id: str, *, include_bytes: bool = False) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT s.*,COUNT(a.asset_id) AS asset_count
                   FROM topology_source_artifacts s
                   LEFT JOIN topology_source_assets a ON a.source_id=s.source_id
                   WHERE s.source_id=? GROUP BY s.source_id""",
                (source_id,),
            ).fetchone()
            result = self._row(row, asset_count=int(row["asset_count"]) if row else 0)
            if result is not None and include_bytes:
                source_bytes = bytes(row["source_bytes"])
                if len(source_bytes) != result["size_bytes"] or hashlib.sha256(source_bytes).hexdigest() != result["sha256"]:
                    raise TopologySourceArtifactError("native source artifact failed its stored size/SHA-256 integrity check")
                result["source_bytes"] = source_bytes
        return result

    def list_assets(self, source_id: str) -> list[dict]:
        with self.database.connection() as connection:
            source = connection.execute(
                "SELECT source_id FROM topology_source_artifacts WHERE source_id=?", (source_id,)
            ).fetchone()
            if source is None:
                raise TopologySourceArtifactNotFound("native source artifact not found")
            rows = connection.execute(
                """SELECT asset_id,source_id,relative_path,media_type,sha256,size_bytes,created_at
                   FROM topology_source_assets WHERE source_id=? ORDER BY relative_path""",
                (source_id,),
            ).fetchall()
        return [{key: row[key] for key in (
            "asset_id", "source_id", "relative_path", "media_type", "sha256", "size_bytes", "created_at",
        )} for row in rows]

    def get_asset_bytes(self, source_id: str, asset_id: str) -> bytes:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT content_bytes,sha256,size_bytes FROM topology_source_assets WHERE source_id=? AND asset_id=?",
                (source_id, asset_id),
            ).fetchone()
        if row is None:
            raise TopologySourceArtifactNotFound("native source asset not found")
        content = bytes(row["content_bytes"])
        if len(content) != row["size_bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise TopologySourceArtifactError("native source asset failed its stored size/SHA-256 integrity check")
        return content
