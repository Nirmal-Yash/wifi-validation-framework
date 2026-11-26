"""Scoped import/export orchestration for native topology source artifacts."""
from __future__ import annotations

import copy
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any

from .topology_presentation import (
    TopologyPresentationConflict,
    TopologyPresentationError,
    TopologyPresentationNotFound,
    TopologyPresentationService,
)
from .topology_source_artifacts import (
    TopologySourceArtifactError,
    TopologySourceArtifactNotFound,
    TopologySourceArtifactService,
)
from .topology_studio import TopologyStudioError, TopologyStudioNotFound, TopologyStudioService
from lib.native_topology.contracts import EncodedNativeTopology, NativeTopologyCodecError
from lib.native_topology.helpers import ensure_source
from lib.native_topology.registry import NativeTopologyCodecRegistry, default_registry


class NativeTopologyInteropError(ValueError):
    """Invalid native file, provenance, or export lifecycle."""


class NativeTopologyInteropNotFound(LookupError):
    """Project-scoped native source or topology revision was not found."""


class NativeTopologyInteropConflict(NativeTopologyInteropError):
    """The selected revisions or native export operation conflict."""


@dataclass(frozen=True, slots=True)
class NativeTopologyExport:
    filename: str
    media_type: str
    content: bytes
    report: dict[str, Any]


class NativeTopologyInteropService:
    """Joins independent native codecs to existing immutable topology/provenance services."""

    MAX_SOURCE_BYTES = TopologySourceArtifactService.MAX_SOURCE_BYTES

    def __init__(
        self,
        database,
        *,
        topology_studio: TopologyStudioService | None = None,
        topology_presentation: TopologyPresentationService | None = None,
        source_artifacts: TopologySourceArtifactService | None = None,
        codec_registry: NativeTopologyCodecRegistry | None = None,
    ) -> None:
        self.database = database
        self.topology_studio = topology_studio or TopologyStudioService(database)
        self.topology_presentation = topology_presentation or TopologyPresentationService(database)
        self.source_artifacts = source_artifacts or TopologySourceArtifactService(database)
        self.codecs = codec_registry or default_registry()

    def list_codecs(self) -> list[dict[str, Any]]:
        return [
            {
                "format_id": item.format_id,
                "codec_name": item.codec_name,
                "codec_version": item.codec_version,
                "extensions": list(item.extensions),
                "supported_versions": list(item.supported_versions),
                "scope": item.scope,
                "external_reopen_required": item.external_reopen_required,
            }
            for item in self.codecs.descriptors()
        ]

    def import_file(
        self,
        *,
        project_id: str,
        name: str,
        filename: str,
        content: bytes,
        scope_type: str = "PROJECT",
        scope_id: str | None = None,
        actor: str,
    ) -> dict[str, Any]:
        raw = ensure_source(content)
        if len(raw) > self.MAX_SOURCE_BYTES:
            raise NativeTopologyInteropError("native project exceeds the configured 50 MiB source limit")
        clean_filename = self.source_artifacts._filename(filename)
        actor = self.source_artifacts._actor(actor)
        try:
            decoded = self.codecs.decode(raw, clean_filename)
            normalized_definition, _definition_json, _definition_hash = self.topology_studio.canonical_payload(
                decoded.topology_definition
            )
            # Validate the entire presentation before creating any Project records.
            # The real artifact ID is assigned only after the canonical revision exists.
            preflight_presentation = copy.deepcopy(decoded.presentation)
            preflight_presentation["source_artifact_id"] = "tsr_" + ("0" * 24)
            normalized_presentation, _presentation_json, _presentation_hash = (
                self.topology_presentation.canonical_payload(
                    preflight_presentation, normalized_definition
                )
            )
            metadata, _metadata_json = self.source_artifacts._metadata(decoded.metadata)
            self.source_artifacts._bytes(raw, "source_bytes", self.MAX_SOURCE_BYTES)
        except (
            NativeTopologyCodecError, TopologyStudioError, TopologyPresentationError,
            TopologySourceArtifactError, TypeError, ValueError,
        ) as exc:
            raise NativeTopologyInteropError(str(exc)) from exc

        try:
            profile = self.topology_studio.create_profile(
                project_id=project_id,
                name=name,
                description=f"Imported {decoded.format_id} native topology ({decoded.format_version})",
                scope_type=scope_type,
                scope_id=scope_id,
                actor=actor,
            )
            revision = self.topology_studio.create_revision(
                profile["profile_id"],
                definition=normalized_definition,
                actor=actor,
            )
            source = self.source_artifacts.record_source_artifact(
                profile["profile_id"],
                revision["revision_id"],
                source_bytes=raw,
                format_id=decoded.format_id,
                format_version=decoded.format_version,
                filename=clean_filename,
                codec_name=next(
                    item.codec_name for item in self.codecs.descriptors()
                    if item.format_id == decoded.format_id
                ),
                codec_version=next(
                    item.codec_version for item in self.codecs.descriptors()
                    if item.format_id == decoded.format_id
                ),
                metadata=metadata,
                assets=decoded.assets,
                actor=actor,
            )
            presentation = copy.deepcopy(normalized_presentation)
            presentation["source_artifact_id"] = source["source_id"]
            saved_presentation = self.topology_presentation.create_revision(
                revision["revision_id"],
                presentation=presentation,
                actor=actor,
            )
        except (TopologyStudioNotFound, TopologyPresentationNotFound, TopologySourceArtifactNotFound) as exc:
            raise NativeTopologyInteropNotFound(str(exc)) from exc
        except (
            TopologyStudioError, TopologyPresentationError, TopologyPresentationConflict,
            TopologySourceArtifactError, TypeError, ValueError,
        ) as exc:
            raise NativeTopologyInteropError(str(exc)) from exc

        return {
            "profile": profile,
            "revision": revision,
            "source": source,
            "presentation": saved_presentation,
            "report": {
                "format_id": decoded.format_id,
                "format_version": decoded.format_version,
                "counts": {
                    "nodes": len(normalized_definition["nodes"]),
                    "links": len(normalized_definition["links"]),
                    "drawings": len(normalized_presentation.get("drawings", [])),
                },
                "warnings": list(decoded.warnings),
                "export_scope": "PRESENTATION_ONLY",
                "external_reopen_required": True,
            },
        }

    def list_sources(self, profile_id: str) -> list[dict[str, Any]]:
        profile = self.topology_studio.get_profile(profile_id)
        if profile is None:
            raise NativeTopologyInteropNotFound("Topology profile not found")
        return self.source_artifacts.list_source_artifacts(profile_id)

    def export_revision(
        self,
        *,
        profile_id: str,
        revision_id: str,
        presentation_id: str,
        source_id: str,
    ) -> NativeTopologyExport:
        profile = self.topology_studio.get_profile(profile_id)
        revision = self.topology_studio.get_revision(revision_id)
        presentation = self.topology_presentation.get_revision(presentation_id)
        if (
            profile is None or revision is None or presentation is None
            or revision["profile_id"] != profile_id
            or presentation["profile_id"] != profile_id
            or presentation["topology_revision_id"] != revision_id
        ):
            raise NativeTopologyInteropNotFound("Native source, topology revision or presentation revision was not found in this profile")
        if revision["status"] != "PUBLISHED":
            raise NativeTopologyInteropConflict("Publish the canonical topology revision before native export")
        if presentation["status"] != "PUBLISHED":
            raise NativeTopologyInteropConflict("Publish the presentation revision before native export")
        if presentation.get("source_artifact_id") != source_id:
            raise NativeTopologyInteropConflict("The selected presentation is not pinned to the requested native source artifact")
        source = self.source_artifacts.get_source_artifact(source_id, include_bytes=True)
        if (
            source is None or source["profile_id"] != profile_id
            or source["topology_revision_id"] != revision_id
        ):
            raise NativeTopologyInteropNotFound("Native source artifact is not associated with this topology revision")
        source_bytes = source.get("source_bytes")
        if not isinstance(source_bytes, bytes) or hashlib.sha256(source_bytes).hexdigest() != source.get("sha256"):
            raise NativeTopologyInteropError("Native source artifact failed its SHA-256 integrity check")
        try:
            encoded: EncodedNativeTopology = self.codecs.encode(
                source["format_id"],
                revision["definition"],
                presentation["presentation"],
                original_source=source_bytes,
                filename=source["filename"],
            )
        except (NativeTopologyCodecError, ValueError, TypeError, KeyError, IndexError) as exc:
            raise NativeTopologyInteropConflict(str(exc)) from exc
        report = {
            "format_id": encoded.format_id,
            "format_version": encoded.format_version,
            "source_sha256": source["sha256"],
            "export_sha256": hashlib.sha256(encoded.content).hexdigest(),
            "source_size_bytes": source["size_bytes"],
            "export_size_bytes": len(encoded.content),
            "losses": list(encoded.losses),
            "codec_read_back": "SOURCE_FIELDS_PRESERVED_AND_PRESENTATION_EDITED",
            "originating_application_reopen": "NOT_VERIFIED",
        }
        return NativeTopologyExport(
            filename=encoded.filename,
            media_type=encoded.media_type,
            content=encoded.content,
            report=report,
        )
