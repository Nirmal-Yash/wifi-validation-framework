"""Explicit GNS3 binding, topology apply and reconciliation orchestration.

The canonical topology remains authoritative. Provider identifiers are recorded
as mappings and never replace logical node/link identifiers.
"""
from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import json
import os
import secrets
from pathlib import Path
from typing import Any, Mapping

from lib.services.gns3_provider import GNS3Provider, GNS3ProviderError
from lib.providers import ProviderCapabilityError, ProviderConnectionRecord, ProviderRegistry, ProviderSessionService, validate_provider_endpoint
from lib.providers.cml import CMLProvider
from lib.services.resource_lock import ResourceLockError, ResourceLockManager


class TopologyApplyError(RuntimeError):
    """A provider binding or topology application could not be completed safely."""


class TopologyApplyNotFound(LookupError):
    """The requested Lab, binding, topology or provider mapping does not exist."""


class TopologyApplyConflict(TopologyApplyError):
    def __init__(self, message: str, *, plan: dict | None = None):
        super().__init__(message)
        self.plan = plan or {}


class TopologyApplyService:
    def __init__(self, database, credential_vault, topology_studio, *, resource_lock_manager=None, provider_registry=None, provider_session_service=None):
        self.database = database
        self.credential_vault = credential_vault
        self.topology_studio = topology_studio
        # Resolve the module-level GNS3Provider lazily to preserve existing injection
        # points while all provider consumers use the common registry.
        self.provider_registry = provider_registry or ProviderRegistry.with_cml(
            gns3_factory=lambda *args, **kwargs: GNS3Provider(*args, **kwargs)
        )
        self.provider_session_service = provider_session_service or ProviderSessionService(
            self.credential_vault, self.provider_registry,
        )
        if resource_lock_manager is None:
            directory = Path(
                os.getenv("NETREGRESS_LOCK_DIRECTORY")
                or (Path(database.path).resolve().parent / "locks")
            )
            resource_lock_manager = ResourceLockManager(directory)
        self.resource_lock_manager = resource_lock_manager

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise TopologyApplyError("actor must contain 1 to 128 printable characters")
        return actor

    def _acquire_lab_lease(self, lab_id: str, owner: str, lease_seconds: float):
        try:
            return self.resource_lock_manager.acquire(
                "lab:" + lab_id, owner[:128], timeout=0.0, lease_seconds=lease_seconds,
            )
        except (ResourceLockError, OSError, ValueError) as exc:
            raise TopologyApplyConflict(
                "Lab is locked by another provider operation; no provider changes were started"
            ) from exc

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _audit(connection, actor: str, action: str, resource_type: str, resource_id: str, details: dict):
        connection.execute(
            """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("AUD-" + secrets.token_hex(12), actor, action, resource_type, resource_id,
             TopologyApplyService._json(details), TopologyApplyService._now()),
        )

    @staticmethod
    def _workspace_id(binding: Mapping[str, Any]) -> str:
        value = binding.get("provider_workspace_id") or binding.get("gns3_project_id")
        if not isinstance(value, str) or not value:
            raise TopologyApplyError("provider binding has no provider workspace identifier")
        return value

    @staticmethod
    def _serialize_binding(row) -> dict | None:
        if row is None:
            return None
        keys = set(row.keys())
        legacy_workspace = row["gns3_project_id"]
        workspace = row["provider_workspace_id"] if "provider_workspace_id" in keys else legacy_workspace
        provider_id = row["provider_id"] if "provider_id" in keys else "gns3"
        return {
            "provider_id": provider_id or "gns3",
            "provider_workspace_id": workspace or legacy_workspace,
            "gns3_project_id": legacy_workspace,
        } | {key: row[key] for key in (
            "binding_id", "project_id", "lab_id", "endpoint_url", "controller_device_id",
            "credential_id", "status", "created_at", "updated_at", "created_by", "updated_by",
        )}

    def get_binding(self, lab_id: str, *, include_archived: bool = False) -> dict | None:
        query = "SELECT * FROM gns3_lab_bindings WHERE lab_id=?"
        if not include_archived:
            query += " AND status='ACTIVE'"
        with self.database.connection() as connection:
            row = connection.execute(query, (lab_id,)).fetchone()
        return self._serialize_binding(row)

    def list_bindings(self, project_id: str) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM gns3_lab_bindings WHERE project_id=? ORDER BY lab_id",
                (project_id,),
            ).fetchall()
        return [self._serialize_binding(row) for row in rows]

    def get_provider_connection(self, lab_id: str, *, include_archived: bool = False) -> dict | None:
        binding = self.get_binding(lab_id, include_archived=include_archived)
        return ProviderConnectionRecord.from_binding(binding).as_dict() if binding else None

    def provider_registry_snapshot(self, project_id: str) -> dict:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id is required")
        connections = [
            ProviderConnectionRecord.from_binding(binding).as_dict()
            for binding in self.list_bindings(project_id)
        ]
        return {"providers": self.provider_registry.list_descriptors(), "connections": connections}

    def _require_provider_capability(self, provider_id: str, capability_id: str) -> None:
        try:
            self.provider_registry.require_capability(provider_id, capability_id)
        except ProviderCapabilityError as exc:
            raise TopologyApplyConflict(str(exc)) from exc

    def bind(
        self, lab_id: str, *, endpoint_url: str, controller_device_id: str,
        credential_id: str, actor: str, provider_id: str = "gns3",
        provider_workspace_id: str | None = None, gns3_project_id: str | None = None,
    ) -> dict:
        """Verify and persist a provider-neutral Project/Lab binding.

        gns3_project_id remains an accepted compatibility alias and is populated
        for every adapter so pre-P06 clients and rows remain readable.
        """
        actor = self._actor(actor)
        lab_id = str(lab_id or "").strip()
        provider_id = str(provider_id or "gns3").strip().lower()
        workspace_id = str(provider_workspace_id or gns3_project_id or "").strip()
        if not lab_id or len(lab_id) > 128:
            raise TopologyApplyError("lab_id is invalid")
        if provider_id not in {"gns3", "cml", "eve-ng"}:
            raise TopologyApplyError("provider_id must be gns3, cml or eve-ng")
        if not workspace_id or len(workspace_id) > 512 or any(ord(char) < 33 for char in workspace_id):
            raise TopologyApplyError("provider_workspace_id is invalid")
        try:
            self.provider_registry.descriptor(provider_id)
            if provider_id == "gns3":
                GNS3Provider._segment(workspace_id, "provider_workspace_id")
            elif provider_id == "cml":
                CMLProvider._segment(workspace_id, "provider_workspace_id")
            endpoint = validate_provider_endpoint(endpoint_url)
        except Exception as exc:
            raise TopologyApplyError("provider is not registered or endpoint is not a permitted private controller URL") from exc

        with self.database.connection() as connection:
            lab = connection.execute(
                """SELECT l.project_id,l.status,p.status AS project_status
                   FROM labs l JOIN projects p ON p.project_id=l.project_id WHERE l.lab_id=?""",
                (lab_id,),
            ).fetchone()
            device = connection.execute(
                "SELECT project_id,lab_id,host,status FROM devices WHERE device_id=?",
                (controller_device_id,),
            ).fetchone()
        if lab is None:
            raise TopologyApplyNotFound("Lab not found")
        if lab["status"] != "ACTIVE" or lab["project_status"] != "ACTIVE":
            raise TopologyApplyConflict("provider bindings require an active Project and Lab")
        if device is None or device["project_id"] != lab["project_id"] or device["lab_id"] != lab_id or device["status"] != "ACTIVE":
            raise TopologyApplyConflict("controller device must be active in the selected Project and Lab")
        try:
            endpoint = validate_provider_endpoint(endpoint_url, expected_host=device["host"])
        except Exception as exc:
            raise TopologyApplyError("provider endpoint must match the registered controller Device and use an approved local/private URL") from exc
        credential = self.credential_vault.get(credential_id)
        if (
            credential is None or credential["project_id"] != lab["project_id"]
            or credential["device_id"] != controller_device_id
            or credential["credential_type"] != "API_TOKEN" or credential["status"] != "ACTIVE"
            or not credential.get("username")
        ):
            raise TopologyApplyConflict("an active API_TOKEN credential for the registered controller device is required")

        def verify(provider):
            self._require_provider_capability(provider_id, "projects.read")
            projects = provider.list_projects()
            if not any(item.get("project_id") == workspace_id for item in projects):
                raise TopologyApplyNotFound("selected provider workspace is not available to this credential")
            return True

        try:
            self.provider_session_service.with_provider(
                {
                    "provider_id": provider_id, "endpoint_url": endpoint,
                    "project_id": lab["project_id"],
                    "provider_workspace_id": workspace_id, "gns3_project_id": workspace_id,
                    "controller_device_id": controller_device_id, "credential_id": credential_id,
                },
                actor, verify,
            )
        except (TopologyApplyNotFound, TopologyApplyConflict):
            raise
        except Exception as exc:
            if isinstance(exc, TopologyApplyError):
                raise
            raise TopologyApplyError("provider binding verification failed; check the private endpoint and OS-vault credential") from exc

        lease = self._acquire_lab_lease(lab_id, "topology-bind:" + actor, 300.0)
        try:
            now = self._now()
            with self.database.transaction(immediate=True) as connection:
                current_device = connection.execute(
                    "SELECT project_id,lab_id,host,status FROM devices WHERE device_id=?",
                    (controller_device_id,),
                ).fetchone()
                current_credential = connection.execute(
                    """SELECT project_id,device_id,credential_type,status,username
                       FROM managed_credentials WHERE credential_id=?""",
                    (credential_id,),
                ).fetchone()
                if (
                    current_device is None or current_device["project_id"] != lab["project_id"]
                    or current_device["lab_id"] != lab_id or current_device["host"] != device["host"]
                    or current_device["status"] != "ACTIVE"
                    or current_credential is None or current_credential["project_id"] != lab["project_id"]
                    or current_credential["device_id"] != controller_device_id
                    or current_credential["credential_type"] != "API_TOKEN"
                    or current_credential["status"] != "ACTIVE" or not current_credential["username"]
                ):
                    raise TopologyApplyConflict("controller Device or API_TOKEN scope changed during binding verification")
                existing = connection.execute(
                    "SELECT binding_id FROM gns3_lab_bindings WHERE lab_id=?", (lab_id,)
                ).fetchone()
                if existing:
                    binding_id = existing["binding_id"]
                    connection.execute(
                        """UPDATE gns3_lab_bindings SET project_id=?,endpoint_url=?,gns3_project_id=?,
                           provider_id=?,provider_workspace_id=?,controller_device_id=?,credential_id=?,
                           status='ACTIVE',updated_at=?,updated_by=? WHERE lab_id=?""",
                        (lab["project_id"], endpoint, workspace_id, provider_id, workspace_id,
                         controller_device_id, credential_id, now, actor, lab_id),
                    )
                    action = "PROVIDER_LAB_BINDING_UPDATED"
                else:
                    binding_id = "pnb_" + secrets.token_hex(12)
                    connection.execute(
                        """INSERT INTO gns3_lab_bindings(
                           binding_id,project_id,lab_id,endpoint_url,gns3_project_id,provider_id,
                           provider_workspace_id,controller_device_id,credential_id,status,created_at,
                           updated_at,created_by,updated_by
                           ) VALUES(?,?,?,?,?,?,?,?,?,'ACTIVE',?,?,?,?)""",
                        (binding_id, lab["project_id"], lab_id, endpoint, workspace_id, provider_id,
                         workspace_id, controller_device_id, credential_id, now, now, actor, actor),
                    )
                    action = "PROVIDER_LAB_BINDING_CREATED"
                self._audit(connection, actor, action, "PROVIDER_LAB_BINDING", binding_id,
                            {"provider_id": provider_id, "provider_workspace_id": workspace_id,
                             "project_id": lab["project_id"], "lab_id": lab_id,
                             "controller_device_id": controller_device_id})
            return self.get_binding(lab_id) or {}
        finally:
            lease.release()

    def archive_binding(self, lab_id: str, *, actor: str) -> dict:
        actor = self._actor(actor)
        lease = self._acquire_lab_lease(lab_id, "topology-binding-archive:" + actor, 300.0)
        try:
            binding = self.get_binding(lab_id)
            if binding is None:
                raise TopologyApplyNotFound("active GNS3 binding not found")
            now = self._now()
            with self.database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    """UPDATE gns3_lab_bindings SET status='ARCHIVED',updated_at=?,updated_by=?
                       WHERE lab_id=? AND status='ACTIVE'""",
                    (now, actor, lab_id),
                )
                if cursor.rowcount != 1:
                    raise TopologyApplyNotFound("active GNS3 binding not found")
                self._audit(connection, actor, "GNS3_LAB_BINDING_ARCHIVED", "GNS3_LAB_BINDING",
                            binding["binding_id"], {"project_id": binding["project_id"], "lab_id": lab_id})
            return self.get_binding(lab_id, include_archived=True) or {}
        finally:
            lease.release()

    def _profile_revision(self, profile_id: str, revision_id: str):
        profile = self.topology_studio.get_profile(profile_id)
        revision = self.topology_studio.get_revision(revision_id)
        if profile is None or revision is None or revision["profile_id"] != profile_id:
            raise TopologyApplyNotFound("topology profile or revision not found")
        if profile["scope_type"] != "LAB" or not profile["lab_id"]:
            raise TopologyApplyConflict("only Lab-scoped topology profiles can be applied to a provider")
        if profile["status"] != "ACTIVE" or revision["status"] != "PUBLISHED":
            raise TopologyApplyConflict("apply requires an active profile and a published immutable revision")
        return profile, revision

    def _with_provider(self, binding: dict, actor: str, callback):
        return self.provider_session_service.with_provider(binding, actor, callback)

    def _snapshot(self, provider, binding: dict, *, template_ids=()) -> dict:
        provider_id = str(binding.get("provider_id") or "gns3")
        for capability_id in (
            "controller.version.read", "projects.read", "templates.read",
            "topology.nodes.read", "topology.links.read", "topology.observed.read",
            "resources.availability.read",
        ):
            self._require_provider_capability(provider_id, capability_id)
        projects = provider.list_projects()
        if not any(item.get("project_id") == self._workspace_id(binding) for item in projects):
            raise TopologyApplyNotFound("bound provider workspace is no longer available")
        observed = provider.get_observed_topology(self._workspace_id(binding))
        if not isinstance(observed, dict) or not isinstance(observed.get("nodes"), list) or not isinstance(observed.get("links"), list):
            raise TopologyApplyError("provider returned an invalid observed-topology snapshot")
        resources = provider.get_resource_availability()
        if not isinstance(resources, dict) or not isinstance(resources.get("computes"), list):
            raise TopologyApplyError("provider returned an invalid resource-availability observation")
        templates = provider.list_templates()
        template_images = {}
        requested_templates = sorted({str(item).strip() for item in template_ids if isinstance(item, str) and item.strip()})
        if requested_templates:
            self._require_provider_capability(provider_id, "templates.images.read")
            available_template_ids = {
                item.get("template_id") for item in templates
                if isinstance(item, Mapping) and isinstance(item.get("template_id"), str)
            }
            for template_id in requested_templates:
                if template_id in available_template_ids:
                    template_images[template_id] = provider.get_template_image_availability(template_id)
                else:
                    template_images[template_id] = {
                        "template_id": template_id, "status": "UNAVAILABLE",
                        "required_images": [], "available_images": [], "missing_images": [],
                        "reason": "template is not present in the current provider catalogue",
                    }
        lifecycle = {}
        for node in observed["nodes"]:
            status = str(node.get("status") or "UNKNOWN").upper()
            lifecycle[status] = lifecycle.get(status, 0) + 1
        return {
            "version": provider.version(),
            "projects": projects,
            "templates": templates,
            "nodes": observed["nodes"],
            "links": observed["links"],
            "resources": resources,
            "node_lifecycle": lifecycle,
            "template_images": template_images,
            "capture_support": provider.capture_support(),
        }

    @staticmethod
    def _provider_name(profile_id: str, logical_id: str) -> str:
        return "NR-" + profile_id[-8:] + "-" + logical_id

    @staticmethod
    def _endpoint(node_id: str, adapter: object, port: object):
        try:
            adapter_number = int(adapter)
            port_number = int(port)
        except (TypeError, ValueError):
            return None
        if not 0 <= adapter_number <= 255 or not 0 <= port_number <= 255:
            return None
        return (str(node_id), adapter_number, port_number)

    @classmethod
    def _signature(cls, provider_link: Mapping[str, Any]):
        endpoints = provider_link.get("nodes")
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            return None
        normalized = []
        for item in endpoints:
            if not isinstance(item, Mapping):
                return None
            endpoint = cls._endpoint(item.get("node_id"), item.get("adapter_number"), item.get("port_number"))
            if endpoint is None:
                return None
            normalized.append(endpoint)
        return tuple(sorted(normalized))

    @staticmethod
    def _port_set(provider_node: Mapping[str, Any]) -> set[tuple[int, int]]:
        ports = provider_node.get("ports")
        if not isinstance(ports, list):
            return set()
        result = set()
        for item in ports:
            if not isinstance(item, Mapping):
                continue
            try:
                adapter = int(item.get("adapter_number"))
                port = int(item.get("port_number"))
            except (TypeError, ValueError):
                continue
            if 0 <= adapter <= 255 and 0 <= port <= 255:
                result.add((adapter, port))
        return result

    def _mappings(self, profile_id: str) -> dict[tuple[str, str], dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM topology_provider_mappings WHERE profile_id=?", (profile_id,)
            ).fetchall()
        return {(row["resource_type"], row["logical_id"]): dict(row) for row in rows}

    def _save_mapping(
        self, *, profile: dict, resource_type: str, logical_id: str,
        provider_resource_id: str, template_id: str | None = None,
    ):
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO topology_provider_mappings(
                   mapping_id,project_id,lab_id,profile_id,resource_type,logical_id,
                   provider_resource_id,template_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(profile_id,resource_type,logical_id) DO UPDATE SET
                   provider_resource_id=excluded.provider_resource_id,
                   template_id=excluded.template_id,updated_at=excluded.updated_at""",
                ("tpm_" + secrets.token_hex(12), profile["project_id"], profile["lab_id"],
                 profile["profile_id"], resource_type, logical_id, provider_resource_id,
                 template_id, now, now),
            )

    def _analyze(self, profile: dict, revision: dict, binding: dict, snapshot: dict) -> tuple[dict, dict]:
        desired = revision["definition"]
        provider_nodes = {
            item.get("node_id"): item for item in snapshot["nodes"]
            if isinstance(item.get("node_id"), str)
        }
        mappings = self._mappings(profile["profile_id"])
        node_ids: dict[str, str] = {}
        adopt_nodes = []
        nodes_to_create = []
        conflicts = []
        templates_by_id = {
            item.get("template_id"): item for item in snapshot["templates"]
            if isinstance(item, Mapping) and isinstance(item.get("template_id"), str)
        }
        resources_by_id = {
            item.get("compute_id"): item for item in snapshot.get("resources", {}).get("computes", [])
            if isinstance(item, Mapping) and isinstance(item.get("compute_id"), str)
        }
        image_by_template = snapshot.get("template_images", {})
        template_compatibility = []
        for node in desired["nodes"]:
            logical_id = node["id"]
            mapping = mappings.get(("NODE", logical_id))
            mapped_id = mapping.get("provider_resource_id") if mapping else None
            template_id = node.get("template_id")
            template = templates_by_id.get(template_id)
            image_check = image_by_template.get(template_id, {}) if isinstance(image_by_template, Mapping) else {}
            compute_id = template.get("compute_id") if isinstance(template, Mapping) else None
            compute = resources_by_id.get(compute_id) if compute_id else None
            compute_connected = compute.get("connected") if isinstance(compute, Mapping) else None
            template_status = "UNMAPPED" if not template_id else "AVAILABLE" if template else "UNAVAILABLE"
            image_status = str(image_check.get("status") or "UNKNOWN").upper()
            template_compatibility.append({
                "logical_node_id": logical_id,
                "template_id": template_id or None,
                "template_name": template.get("name") if isinstance(template, Mapping) else None,
                "template_type": template.get("template_type") if isinstance(template, Mapping) else None,
                "template_status": template_status,
                "compute_id": compute_id,
                "compute_connected": compute_connected,
                "image_status": image_status,
                "missing_images": list(image_check.get("missing_images", [])) if isinstance(image_check, Mapping) else [],
            })
            remote = provider_nodes.get(mapped_id)
            managed_name = self._provider_name(profile["profile_id"], logical_id)
            if remote is not None and remote.get("template_id") != node["template_id"]:
                conflicts.append({
                    "resource_id": logical_id,
                    "reason": "mapped provider node template no longer matches the published revision",
                })
                continue
            if remote is None:
                candidates = [item for item in snapshot["nodes"] if item.get("name") == managed_name]
                if len(candidates) == 1 and candidates[0].get("template_id") == node["template_id"]:
                    remote = candidates[0]
                    adopt_nodes.append({"logical_node_id": logical_id, "provider_node_id": remote["node_id"],
                                        "template_id": node["template_id"]})
                elif len(candidates) > 1:
                    conflicts.append({"resource_id": logical_id, "reason": "multiple provider nodes share the managed identity"})
                elif candidates:
                    conflicts.append({"resource_id": logical_id, "reason": "managed provider node template does not match the published revision"})
            if remote is not None and isinstance(remote.get("node_id"), str):
                node_ids[logical_id] = remote["node_id"]
            else:
                if not node.get("template_id"):
                    conflicts.append({"resource_id": logical_id, "reason": "logical node has no provider template mapping"})
                elif node["template_id"] not in templates_by_id:
                    conflicts.append({"resource_id": logical_id, "reason": "provider template is unavailable"})
                if template and compute_connected is False:
                    conflicts.append({
                        "resource_id": logical_id,
                        "reason": "provider compute assigned to the template is disconnected",
                    })
                if template and image_status == "MISSING":
                    conflicts.append({
                        "resource_id": logical_id,
                        "reason": "one or more required template images are unavailable on the assigned compute",
                    })
                nodes_to_create.append({
                    "logical_node_id": logical_id, "name": node["name"],
                    "provider_name": managed_name, "template_id": node["template_id"],
                    "x": node["x"], "y": node["y"],
                })

        links_by_signature = {}
        occupied = {}
        for link in snapshot["links"]:
            signature = self._signature(link)
            if signature is None:
                continue
            links_by_signature[signature] = link
            for endpoint in signature:
                occupied[endpoint] = signature
        links_to_create = []
        links_pending_nodes = []
        already_present_links = []
        already_present_link_mappings = []
        for link in desired["links"]:
            source_id = node_ids.get(link["source_node_id"])
            target_id = node_ids.get(link["target_node_id"])
            if source_id is None or target_id is None:
                links_pending_nodes.append(link["id"])
                continue
            source = self._endpoint(source_id, link["source_adapter"], link["source_port"])
            target = self._endpoint(target_id, link["target_adapter"], link["target_port"])
            if source is None or target is None:
                conflicts.append({"resource_id": link["id"], "reason": "topology endpoint is invalid"})
                continue
            signature = tuple(sorted((source, target)))
            existing = links_by_signature.get(signature)
            if existing is not None:
                already_present_links.append(link["id"])
                if isinstance(existing.get("link_id"), str):
                    already_present_link_mappings.append({
                        "logical_link_id": link["id"], "provider_link_id": existing["link_id"],
                    })
                continue
            source_node = provider_nodes.get(source_id)
            target_node = provider_nodes.get(target_id)
            if source_node is None or target_node is None:
                conflicts.append({"resource_id": link["id"], "reason": "mapped provider node is not present"})
                continue
            if (source[1], source[2]) not in self._port_set(source_node) or (target[1], target[2]) not in self._port_set(target_node):
                conflicts.append({"resource_id": link["id"], "reason": "requested adapter/port is not exposed by the provider node"})
                continue
            occupied_by = occupied.get(source) or occupied.get(target)
            if occupied_by is not None:
                conflicts.append({"resource_id": link["id"], "reason": "requested adapter/port is occupied by a different provider link"})
                continue
            links_to_create.append({
                "logical_link_id": link["id"], "source_node_id": source_id,
                "source_adapter": source[1], "source_port": source[2],
                "target_node_id": target_id, "target_adapter": target[1],
                "target_port": target[2],
            })
        plan = {
            "binding_id": binding["binding_id"], "lab_id": binding["lab_id"],
            "provider_id": str(binding.get("provider_id") or "gns3"),
            "provider_workspace_id": self._workspace_id(binding),
            "gns3_project_id": self._workspace_id(binding), "profile_id": profile["profile_id"],
            "revision_id": revision["revision_id"], "revision_sha256": revision["content_sha256"],
            "nodes_to_create": nodes_to_create, "adopt_nodes": adopt_nodes,
            "links_to_create": links_to_create, "links_pending_nodes": links_pending_nodes,
            "already_present_nodes": sorted(node_ids), "already_present_links": already_present_links,
            "already_present_link_mappings": already_present_link_mappings,
            "template_compatibility": template_compatibility,
            "resource_availability": snapshot.get("resources", {}),
            "node_lifecycle": snapshot.get("node_lifecycle", {}),
            "conflicts": conflicts, "unmanaged_provider_node_count": len(snapshot["nodes"]) - len(set(node_ids.values())),
            "unmanaged_provider_link_count": len(snapshot["links"]) - len({row.get("provider_resource_id") for row in mappings.values() if row.get("resource_type") == "LINK"}),
            "can_apply": not conflicts,
        }
        return plan, node_ids

    def catalog(self, lab_id: str, *, actor: str) -> dict:
        actor = self._actor(actor)
        binding = self.get_binding(lab_id)
        if binding is None:
            raise TopologyApplyNotFound("active provider binding not found")
        try:
            snapshot = self._with_provider(binding, actor, lambda provider: self._snapshot(provider, binding))
        except Exception as exc:
            if isinstance(exc, TopologyApplyError):
                raise
            raise TopologyApplyError("provider discovery failed") from exc
        provider_id = str(binding.get("provider_id") or "gns3")
        return {
            "binding": binding,
            "connection": ProviderConnectionRecord.from_binding(binding).as_dict(),
            "provider": self.provider_registry.descriptor(provider_id).as_dict(self.provider_registry.capability_registry),
            "catalog": snapshot,
        }

    def provider_interfaces(self, lab_id: str, provider_node_id: str, *, actor: str) -> dict:
        actor = self._actor(actor)
        binding = self.get_binding(lab_id)
        if binding is None:
            raise TopologyApplyNotFound("active provider binding not found")
        provider_id = str(binding.get("provider_id") or "gns3")
        self._require_provider_capability(provider_id, "topology.observed.read")
        self._require_provider_capability(provider_id, "topology.interfaces.read")

        def inspect(provider):
            observed = provider.get_observed_topology(self._workspace_id(binding))
            if not isinstance(observed, dict) or not isinstance(observed.get("nodes"), list):
                raise TopologyApplyError("provider returned an invalid observed node inventory")
            if not any(item.get("node_id") == provider_node_id for item in observed["nodes"]):
                raise TopologyApplyNotFound("provider node is not present in the bound provider workspace")
            interfaces = provider.get_interfaces(self._workspace_id(binding), provider_node_id)
            if not isinstance(interfaces, list):
                raise TopologyApplyError("provider returned an invalid interface inventory")
            return {
                "lab_id": lab_id, "project_id": binding["project_id"],
                "provider_id": str(binding.get("provider_id") or "gns3"),
                "provider_workspace_id": self._workspace_id(binding),
                "provider_project_id": self._workspace_id(binding),
                "provider_node_id": provider_node_id, "interfaces": interfaces,
                "observed_at": self._now(),
            }

        try:
            return self._with_provider(binding, actor, inspect)
        except (TopologyApplyError, TopologyApplyNotFound):
            raise
        except Exception as exc:
            raise TopologyApplyError("provider interface discovery failed") from exc

    def plan(self, profile_id: str, revision_id: str, *, actor: str) -> dict:
        actor = self._actor(actor)
        profile, revision = self._profile_revision(profile_id, revision_id)
        binding = self.get_binding(profile["lab_id"])
        if binding is None or binding["project_id"] != profile["project_id"]:
            raise TopologyApplyNotFound("an active provider binding is required for this Lab")
        def build(provider):
            template_ids = [node.get("template_id") for node in revision["definition"]["nodes"]]
            snapshot = self._snapshot(provider, binding, template_ids=template_ids)
            plan, _node_ids = self._analyze(profile, revision, binding, snapshot)
            return {"plan": plan, "observed": snapshot}
        try:
            return self._with_provider(binding, actor, build)
        except (TopologyApplyError, TopologyApplyNotFound):
            raise
        except Exception as exc:
            raise TopologyApplyError("provider discovery failed; verify the provider binding and OS-vault credential") from exc

    def _insert_apply(self, profile: dict, revision: dict, actor: str, plan: dict, observed: dict) -> str:
        apply_id = "tpa_" + secrets.token_hex(12)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO topology_apply_records(
                   apply_id,project_id,lab_id,profile_id,revision_id,content_sha256,status,
                   plan_json,observed_before_json,observed_after_json,result_json,
                   created_at,started_at,completed_at,created_by
                   ) VALUES(?,?,?,?,?,?,'APPLYING',?,?,?,'{}',?,?,NULL,?)""",
                (apply_id, profile["project_id"], profile["lab_id"], profile["profile_id"],
                 revision["revision_id"], revision["content_sha256"], self._json(plan),
                 self._json(observed), self._json(observed), now, now, actor),
            )
        return apply_id

    def _finish_apply(self, apply_id: str, *, status: str, observed_after: dict, result: dict, actor: str):
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """UPDATE topology_apply_records SET status=?,observed_after_json=?,result_json=?,completed_at=?
                   WHERE apply_id=? AND status='APPLYING'""",
                (status, self._json(observed_after), self._json(result), now, apply_id),
            )
            self._audit(connection, actor, "TOPOLOGY_APPLY_" + status, "TOPOLOGY_APPLY", apply_id,
                        {"status": status, "result": result.get("summary", {})})

    def _reconcile(self, profile: dict, revision: dict, snapshot: dict) -> dict:
        mappings = self._mappings(profile["profile_id"])
        provider_nodes = {
            item.get("node_id"): item for item in snapshot["nodes"] if isinstance(item.get("node_id"), str)
        }
        logical_to_provider = {}
        missing_nodes = []
        mismatched_nodes = []
        for node in revision["definition"]["nodes"]:
            mapping = mappings.get(("NODE", node["id"]))
            provider_id = mapping.get("provider_resource_id") if mapping else None
            if provider_id not in provider_nodes:
                missing_nodes.append(node["id"])
            else:
                logical_to_provider[node["id"]] = provider_id
                if provider_nodes[provider_id].get("template_id") != node["template_id"]:
                    mismatched_nodes.append(node["id"])
        actual_link_signatures = {
            self._signature(item): item for item in snapshot["links"] if self._signature(item) is not None
        }
        missing_links = []
        mismatched_links = []
        logical_to_provider_links = {}
        for link in revision["definition"]["links"]:
            source = logical_to_provider.get(link["source_node_id"])
            target = logical_to_provider.get(link["target_node_id"])
            if source is None or target is None:
                missing_links.append(link["id"])
                continue
            signature = tuple(sorted((
                (source, link["source_adapter"], link["source_port"]),
                (target, link["target_adapter"], link["target_port"]),
            )))
            remote = actual_link_signatures.get(signature)
            mapping = mappings.get(("LINK", link["id"]))
            if remote is None:
                missing_links.append(link["id"])
            elif mapping and isinstance(remote.get("link_id"), str):
                mapped_id = mapping.get("provider_resource_id")
                if mapped_id == remote.get("link_id"):
                    logical_to_provider_links[link["id"]] = mapped_id
                else:
                    mismatched_links.append(link["id"])
            else:
                # An observed provider link without a durable logical mapping is not IN_SYNC.
                mismatched_links.append(link["id"])
        mapped_node_ids = {value for value in logical_to_provider.values()}
        return {
            "profile_id": profile["profile_id"], "revision_id": revision["revision_id"],
            "revision_sha256": revision["content_sha256"], "lab_id": profile["lab_id"],
            "status": "IN_SYNC" if not missing_nodes and not missing_links and not mismatched_nodes and not mismatched_links else "DRIFTED",
            "desired_node_count": len(revision["definition"]["nodes"]),
            "desired_link_count": len(revision["definition"]["links"]),
            "observed_managed_node_count": len(mapped_node_ids),
            "observed_provider_node_count": len(snapshot["nodes"]),
            "observed_provider_link_count": len(snapshot["links"]),
            "missing_nodes": missing_nodes, "missing_links": missing_links,
            "mismatched_nodes": mismatched_nodes, "mismatched_links": mismatched_links,
            "logical_to_provider": logical_to_provider,
            "logical_to_provider_links": logical_to_provider_links,
            "unmanaged_provider_node_count": len(snapshot["nodes"]) - len(mapped_node_ids),
        }

    def reconcile(self, profile_id: str, revision_id: str, *, actor: str) -> dict:
        actor = self._actor(actor)
        profile, revision = self._profile_revision(profile_id, revision_id)
        binding = self.get_binding(profile["lab_id"])
        if binding is None:
            raise TopologyApplyNotFound("an active provider binding is required for this Lab")
        try:
            return self._with_provider(
                binding, actor,
                lambda provider: self._reconcile(profile, revision, self._snapshot(provider, binding)),
            )
        except (TopologyApplyError, TopologyApplyNotFound):
            raise
        except Exception as exc:
            raise TopologyApplyError("GNS3 reconciliation could not complete") from exc

    def apply(
        self, profile_id: str, revision_id: str, *, expected_sha256: str,
        confirmed: bool, actor: str,
    ) -> dict:
        actor = self._actor(actor)
        if confirmed is not True:
            raise TopologyApplyConflict("explicit confirmation is required before provider changes")
        profile, revision = self._profile_revision(profile_id, revision_id)
        if expected_sha256 != revision["content_sha256"]:
            raise TopologyApplyConflict("published topology hash changed; request a fresh dry-run plan")
        binding = self.get_binding(profile["lab_id"])
        if binding is None:
            raise TopologyApplyNotFound("an active provider binding is required for this Lab")
        try:
            lease = self.resource_lock_manager.acquire(
                "lab:" + profile["lab_id"], "topology-apply:" + actor[:80],
                timeout=0.0, lease_seconds=900.0,
            )
        except (ResourceLockError, OSError, ValueError) as exc:
            raise TopologyApplyConflict("Lab is locked by another operation; no provider changes were made") from exc
        try:
            return self._with_provider(
                binding, actor,
                lambda provider: self._apply_locked(provider, profile, revision, binding, actor, expected_sha256),
            )
        finally:
            lease.release()

    def _apply_locked(self, provider, profile, revision, binding, actor, expected_sha256):
        template_ids = [node.get("template_id") for node in revision["definition"]["nodes"]]
        before = self._snapshot(provider, binding, template_ids=template_ids)
        plan, _ = self._analyze(profile, revision, binding, before)
        if revision["content_sha256"] != expected_sha256 or plan["revision_sha256"] != expected_sha256:
            raise TopologyApplyConflict("published topology hash changed; no provider changes were made", plan=plan)
        if not plan["can_apply"]:
            raise TopologyApplyConflict("dry-run found provider conflicts; no provider changes were made", plan=plan)
        provider_id = str(binding.get("provider_id") or "gns3")
        if plan["nodes_to_create"]:
            self._require_provider_capability(provider_id, "topology.nodes.create")
        if plan["links_to_create"]:
            self._require_provider_capability(provider_id, "topology.links.create")
        apply_id = self._insert_apply(profile, revision, actor, plan, before)
        operations = {
            "attempted_nodes": [], "attempted_links": [],
            "created_nodes": [], "recovered_nodes": [], "created_links": [],
            "existing_links": [], "conflicts": [],
        }
        current_snapshot = before
        try:
            for adopted in plan["adopt_nodes"]:
                self._save_mapping(
                    profile=profile, resource_type="NODE", logical_id=adopted["logical_node_id"],
                    provider_resource_id=adopted["provider_node_id"], template_id=adopted["template_id"],
                )
                operations["recovered_nodes"].append(adopted["logical_node_id"])
            for item in plan["nodes_to_create"]:
                operations["attempted_nodes"].append(item["logical_node_id"])
                remote = provider.create_node(
                    self._workspace_id(binding), item["template_id"], name=item["provider_name"],
                    x=item["x"], y=item["y"],
                )
                provider_node_id = remote["node_id"]
                operations["created_nodes"].append(item["logical_node_id"])
                self._save_mapping(
                    profile=profile, resource_type="NODE", logical_id=item["logical_node_id"],
                    provider_resource_id=provider_node_id, template_id=item["template_id"],
                )

            current_snapshot = self._snapshot(provider, binding, template_ids=template_ids)
            refreshed_plan, _ = self._analyze(profile, revision, binding, current_snapshot)
            for existing_link in refreshed_plan["already_present_link_mappings"]:
                self._save_mapping(
                    profile=profile, resource_type="LINK",
                    logical_id=existing_link["logical_link_id"],
                    provider_resource_id=existing_link["provider_link_id"],
                )
            if refreshed_plan["conflicts"]:
                operations["conflicts"].extend(refreshed_plan["conflicts"])
            if refreshed_plan["nodes_to_create"]:
                operations["conflicts"].append({"reason": "one or more provider nodes were not observable after creation"})
            for link in refreshed_plan["links_to_create"] if not operations["conflicts"] else []:
                operations["attempted_links"].append(link["logical_link_id"])
                remote = provider.create_link(
                    self._workspace_id(binding),
                    source_node_id=link["source_node_id"], source_adapter=link["source_adapter"],
                    source_port=link["source_port"], target_node_id=link["target_node_id"],
                    target_adapter=link["target_adapter"], target_port=link["target_port"],
                )
                provider_link_id = remote.get("link_id")
                operations["created_links"].append(link["logical_link_id"])
                if isinstance(provider_link_id, str) and provider_link_id:
                    self._save_mapping(
                        profile=profile, resource_type="LINK",
                        logical_id=link["logical_link_id"], provider_resource_id=provider_link_id,
                    )

            current_snapshot = self._snapshot(provider, binding, template_ids=template_ids)
            reconciliation = self._reconcile(profile, revision, current_snapshot)
            operations["existing_links"] = refreshed_plan["already_present_links"]
            complete = reconciliation["status"] == "IN_SYNC" and not operations["conflicts"]
            status = "APPLIED" if complete else "PARTIAL"
            result = {
                "summary": {
                    "created_nodes": len(operations["created_nodes"]),
                    "recovered_nodes": len(operations["recovered_nodes"]),
                    "created_links": len(operations["created_links"]),
                    "missing_nodes": len(reconciliation["missing_nodes"]),
                    "missing_links": len(reconciliation["missing_links"]),
                    "conflicts": len(operations["conflicts"]),
                },
                "operations": operations,
                "reconciliation": reconciliation,
            }
            self._finish_apply(apply_id, status=status, observed_after=current_snapshot, result=result, actor=actor)
            return self.get_apply(apply_id) or {"apply_id": apply_id, "status": status, "result": result}
        except Exception as exc:
            try:
                current_snapshot = self._snapshot(provider, binding, template_ids=template_ids)
            except Exception:
                current_snapshot = {"observation": "unavailable"}
            attempted = operations["attempted_nodes"] or operations["attempted_links"]
            completed = operations["created_nodes"] or operations["recovered_nodes"] or operations["created_links"]
            status = "PARTIAL" if attempted or completed else "FAILED"
            result = {
                "summary": {
                    "error_type": type(exc).__name__,
                    "completed_operations": (
                        len(operations["created_nodes"]) + len(operations["recovered_nodes"]) + len(operations["created_links"])
                    ),
                    "uncertain_operations": len(operations["attempted_nodes"]) + len(operations["attempted_links"])
                    - len(operations["created_nodes"]) - len(operations["created_links"]),
                },
                "operations": operations,
                "error": "provider operation failed; inspect the apply record and reconcile before retrying",
            }
            self._finish_apply(apply_id, status=status, observed_after=current_snapshot, result=result, actor=actor)
            raise TopologyApplyError("topology application stopped safely; completed provider changes were retained and recorded") from exc

    def get_apply(self, apply_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM topology_apply_records WHERE apply_id=?", (apply_id,)).fetchone()
        if row is None:
            return None
        return {
            key: row[key] for key in (
                "apply_id", "project_id", "lab_id", "profile_id", "revision_id",
                "content_sha256", "status", "created_at", "started_at", "completed_at", "created_by",
            )
        } | {
            "plan": json.loads(row["plan_json"]),
            "observed_before": json.loads(row["observed_before_json"]),
            "observed_after": json.loads(row["observed_after_json"]),
            "result": json.loads(row["result_json"]),
        }

    def list_applies(self, lab_id: str, *, limit: int = 25) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, 100))
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT apply_id FROM topology_apply_records WHERE lab_id=? ORDER BY created_at DESC LIMIT ?",
                (lab_id, limit),
            ).fetchall()
        return [self.get_apply(row["apply_id"]) for row in rows]

    def operate_node(self, profile_id: str, logical_node_id: str, *, action: str, actor: str) -> dict:
        actor = self._actor(actor)
        action = str(action or "").upper()
        if action not in {"START", "STOP"}:
            raise TopologyApplyError("node action must be START or STOP")
        profile = self.topology_studio.get_profile(profile_id)
        if profile is None:
            raise TopologyApplyNotFound("topology profile not found")
        if profile["status"] != "ACTIVE":
            raise TopologyApplyConflict("provider node operations require an active topology profile")
        if profile["scope_type"] != "LAB" or not profile["lab_id"]:
            raise TopologyApplyConflict("provider node operations require a Lab-scoped topology profile")
        binding = self.get_binding(profile["lab_id"])
        if binding is None:
            raise TopologyApplyNotFound("active provider binding not found")
        mappings = self._mappings(profile_id)
        mapping = mappings.get(("NODE", logical_node_id))
        if mapping is None:
            raise TopologyApplyNotFound("logical node has not been mapped to a provider node")
        provider_id = str(binding.get("provider_id") or "gns3")
        self._require_provider_capability(provider_id, "topology.nodes.read")
        self._require_provider_capability(
            provider_id, "topology.nodes.start" if action == "START" else "topology.nodes.stop",
        )
        try:
            lease = self.resource_lock_manager.acquire(
                "lab:" + profile["lab_id"], "topology-node:" + actor[:80],
                timeout=0.0, lease_seconds=300.0,
            )
        except (ResourceLockError, OSError, ValueError) as exc:
            raise TopologyApplyConflict("Lab is locked by another operation") from exc
        try:
            def operate(provider):
                nodes = provider.list_nodes(self._workspace_id(binding))
                remote = next((item for item in nodes if item.get("node_id") == mapping["provider_resource_id"]), None)
                if remote is None:
                    raise TopologyApplyNotFound("mapped provider node is no longer present")
                current = str(remote.get("status", "")).lower()
                already = (action == "START" and current in {"started", "running"}) or (action == "STOP" and current in {"stopped", "suspended"})
                if not already:
                    if action == "START":
                        provider.start_node(self._workspace_id(binding), mapping["provider_resource_id"])
                    else:
                        provider.stop_node(self._workspace_id(binding), mapping["provider_resource_id"])
                refreshed = provider.list_nodes(self._workspace_id(binding))
                after = next((item for item in refreshed if item.get("node_id") == mapping["provider_resource_id"]), None)
                if after is None:
                    raise TopologyApplyError("provider node disappeared during the explicit lifecycle operation")
                observed_state = str(after.get("status", "")).lower()
                accepted_states = {"started", "running"} if action == "START" else {"stopped", "suspended"}
                if observed_state not in accepted_states:
                    raise TopologyApplyError("provider node did not reach the explicitly requested lifecycle state")
                return {"logical_node_id": logical_node_id, "provider_node_id": mapping["provider_resource_id"],
                        "action": action, "status": after.get("status"), "already_in_requested_state": already}
            result = self._with_provider(binding, actor, operate)
            with self.database.transaction(immediate=True) as connection:
                self._audit(connection, actor, "GNS3_NODE_" + action, "TOPOLOGY_NODE",
                            logical_node_id, {"profile_id": profile_id, "lab_id": profile["lab_id"],
                                              "provider_node_id": mapping["provider_resource_id"]})
            return result
        except (TopologyApplyError, TopologyApplyNotFound):
            raise
        except Exception as exc:
            raise TopologyApplyError("explicit provider node operation failed") from exc
        finally:
            lease.release()
