"""Project-scoped deterministic compilation of published Network Intent revisions."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Mapping

from lib.network_config import (
    AdapterCompileError, AdapterResolutionError, NetworkConfigAdapterRegistry,
)
from lib.services.device_inventory import DeviceInventoryService


class NetworkIntentCompilationError(ValueError):
    """Invalid compiler request or unsafe baseline artifact."""


class NetworkIntentCompilerService:
    """Compile immutable P08 revisions to vendor configuration without applying them."""

    COMPILER_VERSION = "1.0.0"
    MAX_BASELINE_BYTES = 1_000_000
    MAX_ARTIFACT_BYTES = 500_000
    MAX_TOTAL_ARTIFACT_BYTES = 2_000_000
    MAX_ARTIFACTS = 128
    _SECRET_LINE = re.compile(
        r"(?i)(?:^|\s)(?:password|passwd|secret|token|community|private[-_ ]key|api[-_ ]key)\s+(?:\S|['\"]).{3,}"
    )
    _PATH = re.compile(r"^[A-Za-z0-9_./-]{1,200}$")

    def __init__(
        self,
        database,
        network_intent,
        device_inventory: DeviceInventoryService | None = None,
        registry: NetworkConfigAdapterRegistry | None = None,
    ) -> None:
        self.database = database
        self.network_intent = network_intent
        self.devices = device_inventory or DeviceInventoryService(database)
        self.registry = registry or NetworkConfigAdapterRegistry()

    @classmethod
    def _normalize_baseline(cls, baseline: object) -> dict[str, str]:
        if baseline is None:
            return {}
        if not isinstance(baseline, Mapping) or len(baseline) > cls.MAX_ARTIFACTS:
            raise NetworkIntentCompilationError("baseline_artifacts must be an object with at most 128 entries")
        result: dict[str, str] = {}
        total = 0
        for raw_path, content in baseline.items():
            if not isinstance(raw_path, str) or not cls._PATH.fullmatch(raw_path):
                raise NetworkIntentCompilationError("baseline artifact path contains unsupported characters")
            path = PurePosixPath(raw_path)
            if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
                raise NetworkIntentCompilationError("baseline artifact path must be a confined relative path")
            if not isinstance(content, str):
                raise NetworkIntentCompilationError("baseline artifact content must be text")
            encoded = content.encode("utf-8")
            total += len(encoded)
            if len(encoded) > cls.MAX_ARTIFACT_BYTES or total > cls.MAX_BASELINE_BYTES:
                raise NetworkIntentCompilationError("baseline artifact content exceeds the configured size limit")
            if cls._SECRET_LINE.search(content):
                raise NetworkIntentCompilationError("baseline appears to contain a credential or secret; remove it before comparison")
            result[path.as_posix()] = content
        return result

    @staticmethod
    def _blocked(
        profile_id: str,
        revision_id: str,
        diagnostics: list[dict],
        *,
        project_id: str | None = None,
        intent_sha256: str | None = None,
        topology_content_sha256: str | None = None,
        validation: Mapping[str, Any] | None = None,
    ) -> dict:
        return {
            "status": "BLOCKED",
            "valid": False,
            "project_id": project_id,
            "profile_id": profile_id,
            "revision_id": revision_id,
            "compiler_version": NetworkIntentCompilerService.COMPILER_VERSION,
            "intent_sha256": intent_sha256,
            "topology_content_sha256": topology_content_sha256,
            "compile_only": True,
            "application_performed": False,
            "ready_for_application": False,
            "artifacts": [],
            "adapters": [],
            "diagnostics": diagnostics,
            "validation": {
                "capability_status": validation.get("capability_status"),
                "required_capabilities": validation.get("required_capabilities", {}),
            } if validation else None,
        }

    @staticmethod
    def _node_intent(intent: Mapping[str, Any], node_id: str) -> dict[str, Any]:
        scoped = {
            "logical_node_id": node_id,
            "schema_version": intent["schema_version"],
        }
        for section in (
            "interfaces", "static_routes", "ospf", "bgp", "aggregations",
            "firewall_zones", "firewall_rules", "service_references",
            "linux_bridges", "linux_vlan_interfaces",
        ):
            scoped[section] = [
                item for item in intent.get(section, [])
                if item.get("logical_node_id") == node_id
            ]
        used_segments = {
            item.get("segment_id") for item in scoped["interfaces"] if item.get("segment_id")
        }
        used_vlans = {
            item.get("access_vlan_id") for item in scoped["interfaces"] if item.get("access_vlan_id")
        }
        for item in scoped["interfaces"]:
            used_vlans.update(item.get("allowed_vlans", []) or [])
        scoped["segments"] = [
            item for item in intent.get("segments", [])
            if item["segment_id"] in used_segments or item.get("vlan_id") in used_vlans
        ]
        return scoped

    @staticmethod
    def _additional_required_features(intent: Mapping[str, Any]) -> set[str]:
        # P08 already derives VLAN capability requirements from ACCESS/TRUNK
        # interface intent. A standalone segment declaration is not a device
        # operation and must not invent an additional capability requirement.
        return set()

    @staticmethod
    def _artifact_path(node_id: str, device_id: str, relative_path: str) -> str:
        if (
            not isinstance(relative_path, str)
            or not NetworkIntentCompilerService._PATH.fullmatch(relative_path)
        ):
            raise NetworkIntentCompilationError("adapter returned an unsafe artifact path")
        parsed = PurePosixPath(relative_path)
        if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
            raise NetworkIntentCompilationError("adapter returned a non-confined artifact path")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", node_id) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", device_id):
            raise NetworkIntentCompilationError("target identity cannot be represented in an artifact path")
        return f"targets/{node_id}-{device_id}/{parsed.as_posix()}"

    @staticmethod
    def _diff(path: str, previous: str | None, current: str) -> tuple[str, str]:
        if previous is None:
            change_type = "NEW"
            before = []
        elif previous == current:
            return "UNCHANGED", ""
        else:
            change_type = "CHANGED"
            before = previous.splitlines(keepends=True)
        after = current.splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(
            before, after,
            fromfile=f"{path}.baseline" if previous is not None else "/dev/null",
            tofile=path,
            lineterm="\n",
        ))
        return change_type, diff

    def list_adapters(self) -> list[dict]:
        return self.registry.list_descriptors()

    def compile_revision(
        self,
        profile_id: str,
        revision_id: str,
        *,
        baseline_artifacts: Mapping[str, str] | None = None,
    ) -> dict:
        baseline = self._normalize_baseline(baseline_artifacts)
        profile = self.network_intent.get_profile(profile_id)
        if profile is None:
            return self._blocked(profile_id, revision_id, [{
                "code": "NETWORK_INTENT_PROFILE_NOT_FOUND",
                "severity": "ERROR", "message": "Network Intent profile was not found",
            }])
        if profile["status"] != "ACTIVE":
            return self._blocked(profile_id, revision_id, [{
                "code": "NETWORK_INTENT_PROFILE_ARCHIVED",
                "severity": "ERROR", "message": "Archived Network Intent profiles cannot be compiled",
            }], project_id=profile["project_id"])
        revision = self.network_intent.get_revision(revision_id)
        if revision is None or revision["profile_id"] != profile_id:
            return self._blocked(profile_id, revision_id, [{
                "code": "NETWORK_INTENT_REVISION_NOT_FOUND",
                "severity": "ERROR", "message": "Revision was not found in the selected Network Intent profile",
            }], project_id=profile["project_id"])
        if revision["status"] != "PUBLISHED":
            return self._blocked(
                profile_id, revision_id, [{
                    "code": "NETWORK_INTENT_REVISION_NOT_PUBLISHED",
                    "severity": "ERROR", "message": "Only a published immutable Network Intent revision can be compiled",
                }],
                project_id=profile["project_id"], intent_sha256=revision["intent_sha256"],
                topology_content_sha256=revision["topology_content_sha256"],
            )

        project_id = profile["project_id"]
        validation = self.network_intent.validate(
            project_id,
            revision["topology_revision_id"],
            revision["definition"],
            profile_id=profile_id,
            evaluate_capabilities=True,
        )
        if (
            not validation.get("valid")
            or not validation.get("ready_for_compilation")
            or validation.get("intent_sha256") != revision["intent_sha256"]
            or validation.get("topology_content_sha256") != revision["topology_content_sha256"]
        ):
            diagnostics = list(validation.get("diagnostics") or [])
            if validation.get("intent_sha256") != revision["intent_sha256"] and validation.get("intent_sha256"):
                diagnostics.append({
                    "code": "INTENT_HASH_MISMATCH", "severity": "ERROR",
                    "message": "Validated intent hash does not match the immutable published revision",
                })
            if validation.get("topology_content_sha256") != revision["topology_content_sha256"] and validation.get("topology_content_sha256"):
                diagnostics.append({
                    "code": "TOPOLOGY_HASH_MISMATCH", "severity": "ERROR",
                    "message": "Validated topology hash does not match the immutable published revision",
                })
            return self._blocked(
                profile_id, revision_id, diagnostics or [{
                    "code": "NETWORK_INTENT_NOT_READY", "severity": "ERROR",
                    "message": "Published intent is not ready for compilation",
                }],
                project_id=project_id, intent_sha256=revision["intent_sha256"],
                topology_content_sha256=revision["topology_content_sha256"], validation=validation,
            )

        intent = validation["normalized_intent"]
        targets = list(intent.get("targets", []))
        if not targets:
            return self._blocked(profile_id, revision_id, [{
                "code": "COMPILER_TARGET_REQUIRED", "severity": "ERROR",
                "message": "At least one logical topology node must be bound to a managed Device before compilation",
            }], project_id=project_id, intent_sha256=revision["intent_sha256"],
                topology_content_sha256=revision["topology_content_sha256"], validation=validation)

        staged_artifacts: list[dict] = []
        adapter_entries: dict[str, dict] = {}
        diagnostics: list[dict] = []
        total_bytes = 0
        for target in sorted(targets, key=lambda item: item["logical_node_id"]):
            node_id, device_id = target["logical_node_id"], target["device_id"]
            device = self.devices.get(device_id)
            if device is None or device.get("project_id") != project_id or device.get("status") != "ACTIVE":
                diagnostics.append({
                    "code": "COMPILER_TARGET_DEVICE_UNAVAILABLE", "severity": "ERROR",
                    "logical_node_id": node_id, "device_id": device_id,
                    "message": "Target Device is missing, archived, or outside this Project",
                })
                continue
            reports = self.network_intent.list_capability_reports(project_id, device_id=device_id)
            report = reports[0] if reports else None
            if report is None:
                diagnostics.append({
                    "code": "COMPILER_CAPABILITY_REPORT_REQUIRED", "severity": "ERROR",
                    "logical_node_id": node_id, "device_id": device_id,
                    "message": "A current adapter-observed platform and capability report is required",
                })
                continue
            try:
                adapter = self.registry.resolve(device, report)
            except AdapterResolutionError as exc:
                diagnostics.append({
                    "code": exc.code, "severity": "ERROR",
                    "logical_node_id": node_id, "device_id": device_id,
                    "message": str(exc),
                })
                continue
            node_intent = self._node_intent(intent, node_id)
            required = set(validation.get("required_capabilities", {}).get(node_id, []))
            required.update(self._additional_required_features(node_intent))
            observed_features = report.get("capabilities", {})
            unknown_observations = sorted(
                feature for feature in required
                if not isinstance(observed_features.get(feature), Mapping)
                or observed_features[feature].get("status") != "SUPPORTED"
            )
            if unknown_observations:
                diagnostics.extend({
                    "code": "COMPILER_CAPABILITY_NOT_OBSERVED", "severity": "ERROR",
                    "logical_node_id": node_id, "device_id": device_id,
                    "feature_id": feature,
                    "message": f"Latest adapter observation does not explicitly report {feature} as SUPPORTED",
                } for feature in unknown_observations)
                continue
            unsupported = sorted(required - set(adapter.supported_features(device)))
            if unsupported:
                diagnostics.extend({
                    "code": "ADAPTER_FEATURE_UNSUPPORTED", "severity": "ERROR",
                    "logical_node_id": node_id, "device_id": device_id,
                    "feature_id": feature,
                    "message": f"Adapter {adapter.descriptor.adapter_id} cannot safely compile required feature {feature}",
                } for feature in unsupported)
                continue
            try:
                files = adapter.compile_target(device, node_intent)
            except AdapterCompileError as exc:
                diagnostics.append({
                    "code": exc.code, "severity": "ERROR",
                    "logical_node_id": node_id, "device_id": device_id,
                    "feature_id": exc.feature_id,
                    "message": str(exc),
                })
                continue
            except (TypeError, ValueError, KeyError) as exc:
                diagnostics.append({
                    "code": "ADAPTER_COMPILATION_FAILED", "severity": "ERROR",
                    "logical_node_id": node_id, "device_id": device_id,
                    "message": f"Adapter rejected the intent safely: {type(exc).__name__}",
                })
                continue
            if not isinstance(files, Mapping) or not files:
                diagnostics.append({
                    "code": "ADAPTER_NO_ARTIFACTS", "severity": "ERROR",
                    "logical_node_id": node_id, "device_id": device_id,
                    "message": "Adapter did not produce a configuration artifact for this target",
                })
                continue
            descriptor = adapter.descriptor.as_dict()
            adapter_entries[descriptor["adapter_id"]] = descriptor
            for relative_path, content in sorted(files.items()):
                if not isinstance(content, str) or not content.strip():
                    diagnostics.append({
                        "code": "ADAPTER_EMPTY_ARTIFACT", "severity": "ERROR",
                        "logical_node_id": node_id, "device_id": device_id,
                        "message": "Adapter returned an empty or non-text artifact",
                    })
                    continue
                encoded = content.encode("utf-8")
                if len(encoded) > self.MAX_ARTIFACT_BYTES:
                    diagnostics.append({
                        "code": "ADAPTER_ARTIFACT_TOO_LARGE", "severity": "ERROR",
                        "logical_node_id": node_id, "device_id": device_id,
                        "message": "An adapter artifact exceeded the 500,000-byte limit",
                    })
                    continue
                total_bytes += len(encoded)
                if total_bytes > self.MAX_TOTAL_ARTIFACT_BYTES or len(staged_artifacts) >= self.MAX_ARTIFACTS:
                    diagnostics.append({
                        "code": "COMPILATION_OUTPUT_LIMIT", "severity": "ERROR",
                        "logical_node_id": node_id, "device_id": device_id,
                        "message": "Compilation exceeded its total artifact or byte limit",
                    })
                    break
                path = self._artifact_path(node_id, device_id, relative_path)
                digest = hashlib.sha256(encoded).hexdigest()
                change_type, diff = self._diff(path, baseline.get(path), content)
                staged_artifacts.append({
                    "path": path, "media_type": "text/plain; charset=utf-8",
                    "content": content, "sha256": digest,
                    "change_type": change_type, "diff": diff,
                })
        if any(item.get("severity") == "ERROR" for item in diagnostics):
            return self._blocked(
                profile_id, revision_id, diagnostics,
                project_id=project_id, intent_sha256=revision["intent_sha256"],
                topology_content_sha256=revision["topology_content_sha256"], validation=validation,
            )

        staged_artifacts.sort(key=lambda item: item["path"])
        orphaned = sorted(set(baseline) - {item["path"] for item in staged_artifacts})
        output_identity = {
            "profile_id": profile_id,
            "revision_id": revision_id,
            "intent_sha256": revision["intent_sha256"],
            "topology_content_sha256": revision["topology_content_sha256"],
            "compiler_version": self.COMPILER_VERSION,
            "adapters": [adapter_entries[key] for key in sorted(adapter_entries)],
            "artifacts": [{"path": item["path"], "sha256": item["sha256"]} for item in staged_artifacts],
        }
        compilation_digest = hashlib.sha256(
            json.dumps(output_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        change_counts = {
            kind.lower(): sum(1 for item in staged_artifacts if item["change_type"] == kind)
            for kind in ("NEW", "CHANGED", "UNCHANGED")
        }
        return {
            "status": "COMPILED",
            "valid": True,
            "project_id": project_id,
            "profile_id": profile_id,
            "revision_id": revision_id,
            "compilation_id": "ncc_" + compilation_digest[:24],
            "compiler_version": self.COMPILER_VERSION,
            "intent_sha256": revision["intent_sha256"],
            "topology_content_sha256": revision["topology_content_sha256"],
            "capability_status": validation.get("capability_status"),
            "compile_only": True,
            "application_performed": False,
            "ready_for_application": False,
            "adapters": [adapter_entries[key] for key in sorted(adapter_entries)],
            "artifacts": staged_artifacts,
            "diagnostics": diagnostics,
            "change_summary": change_counts,
            "orphaned_baseline_files": orphaned,
            "validation": {
                "required_capabilities": validation.get("required_capabilities", {}),
                "capability_status": validation.get("capability_status"),
            },
        }
