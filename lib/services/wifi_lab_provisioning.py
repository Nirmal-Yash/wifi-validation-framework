"""Incremental Python migration of the protected Wi-Fi lab GNS3 operations.

The original shell entry point remains the compatibility owner for host
networking, Docker guest configuration and mac80211_hwsim. This service owns
the reusable GNS3 discovery, management-link and node lifecycle operations.
It never deletes, stops or rewires provider resources.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import secrets
import time
from typing import Any, Callable, Mapping

from lib.services.gns3_provider import GNS3Provider, GNS3ProviderError
from lib.services.resource_lock import ResourceLockError, ResourceLockManager
from lib.providers import ProviderRegistry, ProviderSessionService


class WiFiLabProvisioningError(RuntimeError):
    """A Wi-Fi lab provisioning action was rejected or failed safely."""


class WiFiLabProvisioningConflict(WiFiLabProvisioningError):
    """The provider snapshot has missing resources or unsafe conflicts."""


class WiFiLabProvisioningNotFound(LookupError):
    """The Lab or its registered GNS3 provider binding does not exist."""


class WiFiLabProvisioningService:
    REQUIRED_NODE_NAMES = ("frr-router", "hostapd-ap", "wifi-client", "monitor")
    START_ORDER = ("Switch1", "Cloud", "frr-router", "hostapd-ap", "wifi-client", "monitor")

    def __init__(
        self, database, credential_vault, *, resource_lock_manager=None,
        provider_factory: Callable[..., GNS3Provider] | None = None,
        provider_registry=None, provider_session_service=None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.database = database
        self.credential_vault = credential_vault
        self.provider_registry = provider_registry or ProviderRegistry.with_gns3(
            factory=provider_factory or GNS3Provider,
        )
        self.provider_session_service = provider_session_service or ProviderSessionService(
            self.credential_vault, self.provider_registry,
        )
        self.sleep = sleep
        if resource_lock_manager is None:
            from pathlib import Path
            import os
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
            raise WiFiLabProvisioningError("actor must contain 1 to 128 printable characters")
        return actor

    def _binding(self, lab_id: str) -> dict:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM gns3_lab_bindings WHERE lab_id=? AND status='ACTIVE'",
                (lab_id,),
            ).fetchone()
        if row is None:
            raise WiFiLabProvisioningNotFound("active GNS3 provider binding not found for this Lab")
        return dict(row)

    def _with_provider(self, binding: dict, actor: str, callback):
        return self.provider_session_service.with_provider(binding, actor, callback)

    def _require_provider_capability(self, binding: Mapping[str, Any], capability_id: str) -> None:
        self.provider_registry.require_capability(
            str(binding.get("provider_id") or "gns3"), capability_id,
        )

    @staticmethod
    def _observed_topology(provider, project_id: str) -> tuple[list[dict], list[dict]]:
        observed = provider.get_observed_topology(project_id)
        if (
            not isinstance(observed, dict)
            or not isinstance(observed.get("nodes"), list)
            or not isinstance(observed.get("links"), list)
        ):
            raise WiFiLabProvisioningError("provider returned an invalid observed-topology snapshot")
        return observed["nodes"], observed["links"]

    @staticmethod
    def _port_set(node: Mapping[str, Any]) -> set[tuple[int, int]]:
        ports = node.get("ports")
        if not isinstance(ports, list):
            return set()
        result = set()
        for item in ports:
            if not isinstance(item, Mapping):
                continue
            try:
                adapter, port = int(item.get("adapter_number")), int(item.get("port_number"))
            except (TypeError, ValueError):
                continue
            if 0 <= adapter <= 255 and 0 <= port <= 255:
                result.add((adapter, port))
        return result

    @staticmethod
    def _used_ports(links: list[dict]) -> set[tuple[str, int, int]]:
        result = set()
        for link in links:
            endpoints = link.get("nodes")
            if not isinstance(endpoints, list):
                continue
            for endpoint in endpoints:
                if not isinstance(endpoint, Mapping):
                    continue
                try:
                    key = (
                        str(endpoint["node_id"]),
                        int(endpoint["adapter_number"]),
                        int(endpoint["port_number"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                result.add(key)
        return result

    @classmethod
    def analyze_snapshot(
        cls, *, project_id: str, project_status: str,
        nodes: list[dict], links: list[dict],
    ) -> dict:
        """Build a non-mutating plan from an observed GNS3 snapshot."""
        by_name = {
            item.get("name"): item for item in nodes
            if isinstance(item, Mapping) and isinstance(item.get("name"), str)
        }
        missing = [name for name in cls.REQUIRED_NODE_NAMES if name not in by_name]
        conflicts = []
        if project_status != "opened":
            conflicts.append({
                "code": "GNS3_PROJECT_NOT_OPEN",
                "message": "Open the bound GNS3 project before provisioning its nodes",
            })

        client = by_name.get("wifi-client")
        client_node_id = client.get("node_id") if client else None
        client_ports = cls._port_set(client or {})
        if client and (1, 0) not in client_ports:
            conflicts.append({
                "code": "CLIENT_MANAGEMENT_ADAPTER_MISSING",
                "message": "wifi-client must expose adapter 1, port 0 for the management network",
            })

        management_link = None
        used = cls._used_ports(links)
        if client_node_id:
            for link in links:
                endpoints = link.get("nodes")
                if isinstance(endpoints, list) and any(
                    isinstance(endpoint, Mapping)
                    and endpoint.get("node_id") == client_node_id
                    and endpoint.get("adapter_number") == 1
                    and endpoint.get("port_number") == 0
                    for endpoint in endpoints
                ):
                    management_link = link.get("link_id") or "observed"
                    break

        switch = by_name.get("Switch1")
        free_switch_port = None
        if management_link is None and switch and isinstance(switch.get("node_id"), str):
            switch_id = switch["node_id"]
            for adapter, port in sorted(cls._port_set(switch)):
                if (switch_id, adapter, port) not in used:
                    free_switch_port = (adapter, port)
                    break
        if management_link is None and free_switch_port is None:
            conflicts.append({
                "code": "MANAGEMENT_LINK_REQUIRES_OPERATOR",
                "message": "No free Switch1 port is available; connect wifi-client eth1 to the management network manually",
            })

        start_nodes = []
        for name in cls.START_ORDER:
            node = by_name.get(name)
            if not node or not isinstance(node.get("node_id"), str):
                continue
            if str(node.get("status", "")).lower() not in {"started", "running"}:
                start_nodes.append({
                    "name": name,
                    "node_id": node["node_id"],
                })

        return {
            "project_id": project_id,
            "project_status": project_status,
            "required_nodes": [
                {"name": name, "node_id": by_name[name].get("node_id"), "status": by_name[name].get("status")}
                for name in cls.REQUIRED_NODE_NAMES if name in by_name
            ],
            "missing_nodes": missing,
            "management_link": {
                "status": "PRESENT" if management_link is not None else "MISSING",
                "provider_link_id": management_link,
                "client_node_id": client_node_id,
                "switch_node_id": switch.get("node_id") if switch else None,
                "switch_adapter": free_switch_port[0] if free_switch_port else None,
                "switch_port": free_switch_port[1] if free_switch_port else None,
            },
            "nodes_to_start": start_nodes,
            "conflicts": conflicts,
            "can_apply": not missing and not conflicts,
            "mutations": {
                "create_management_link": management_link is None and free_switch_port is not None,
                "start_node_ids": [item["node_id"] for item in start_nodes],
            },
            "safety": {
                "deletes_resources": False,
                "stops_nodes": False,
                "disconnects_or_rewires_links": False,
                "requires_explicit_confirmation": True,
            },
        }

    def plan(self, lab_id: str, *, actor: str) -> dict:
        actor = self._actor(actor)
        binding = self._binding(str(lab_id))
        try:
            def inspect(provider):
                self._require_provider_capability(binding, "projects.read")
                self._require_provider_capability(binding, "topology.observed.read")
                projects = provider.list_projects()
                project = next(
                    (item for item in projects if item.get("project_id") == binding["gns3_project_id"]),
                    None,
                )
                if project is None:
                    raise WiFiLabProvisioningNotFound("bound GNS3 project is not visible to the linked controller credential")
                nodes, links = self._observed_topology(provider, binding["gns3_project_id"])
                result = self.analyze_snapshot(
                    project_id=binding["gns3_project_id"],
                    project_status=str(project.get("status", "")),
                    nodes=nodes,
                    links=links,
                )
                result["lab_id"] = lab_id
                result["binding_id"] = binding["binding_id"]
                result["provider_node_count"] = len(nodes)
                result["provider_link_count"] = len(links)
                return result
            return self._with_provider(binding, actor, inspect)
        except (WiFiLabProvisioningError, WiFiLabProvisioningNotFound):
            raise
        except Exception as exc:
            raise WiFiLabProvisioningError(
                "GNS3 Wi-Fi lab discovery failed; verify the private provider binding and OS-vault credential"
            ) from exc

    def apply(self, lab_id: str, *, confirmed: bool, actor: str) -> dict:
        actor = self._actor(actor)
        if confirmed is not True:
            raise WiFiLabProvisioningConflict("explicit confirmation is required before provisioning")
        binding = self._binding(str(lab_id))
        try:
            lease = self.resource_lock_manager.acquire(
                "lab:" + str(lab_id), "wifi-provision:" + actor[:80],
                timeout=0.0, lease_seconds=600.0,
            )
        except (ResourceLockError, OSError, ValueError) as exc:
            raise WiFiLabProvisioningConflict(
                "Lab is locked by another provider operation; no GNS3 changes were started"
            ) from exc

        try:
            def execute(provider):
                self._require_provider_capability(binding, "projects.read")
                self._require_provider_capability(binding, "topology.observed.read")
                projects = provider.list_projects()
                project = next(
                    (item for item in projects if item.get("project_id") == binding["gns3_project_id"]),
                    None,
                )
                if project is None:
                    raise WiFiLabProvisioningNotFound("bound GNS3 project is no longer available")
                if project.get("status") != "opened":
                    raise WiFiLabProvisioningConflict(
                        "bound GNS3 project is closed; open it in GNS3 and request a fresh plan"
                    )
                before_nodes, before_links = self._observed_topology(provider, binding["gns3_project_id"])
                plan = self.analyze_snapshot(
                    project_id=binding["gns3_project_id"],
                    project_status=str(project.get("status", "")),
                    nodes=before_nodes,
                    links=before_links,
                )
                if not plan["can_apply"]:
                    raise WiFiLabProvisioningConflict(
                        "GNS3 preflight found missing required nodes or unsafe management-link conflicts"
                    )

                operations = {"created_management_link": False, "started_nodes": [], "already_running_nodes": []}
                link = plan["management_link"]
                if plan["mutations"]["create_management_link"]:
                    self._require_provider_capability(binding, "topology.links.create")
                    provider.create_link(
                        binding["gns3_project_id"],
                        source_node_id=link["client_node_id"],
                        source_adapter=1,
                        source_port=0,
                        target_node_id=link["switch_node_id"],
                        target_adapter=link["switch_adapter"],
                        target_port=link["switch_port"],
                    )
                    _observed_nodes, observed = self._observed_topology(provider, binding["gns3_project_id"])
                    used = self._used_ports(observed)
                    expected = {
                        (link["client_node_id"], 1, 0),
                        (link["switch_node_id"], link["switch_adapter"], link["switch_port"]),
                    }
                    if not any(expected.issubset({
                        (str(endpoint.get("node_id")), int(endpoint.get("adapter_number", -1)),
                         int(endpoint.get("port_number", -1)))
                        for endpoint in item.get("nodes", []) if isinstance(endpoint, Mapping)
                    }) for item in observed):
                        raise WiFiLabProvisioningError(
                            "GNS3 management link was not observable after creation"
                        )
                    operations["created_management_link"] = True

                # Provider actions remain additive and ordered. Start infrastructure
                # before the Docker-backed nodes so their interfaces can attach.
                for item in plan["required_nodes"]:
                    pass
                for item in self.START_ORDER:
                    node = next((node for node in before_nodes if node.get("name") == item), None)
                    if node is None:
                        continue
                    node_id = node.get("node_id")
                    status = str(node.get("status", "")).lower()
                    if status in {"started", "running"}:
                        operations["already_running_nodes"].append(item)
                        continue
                    self._require_provider_capability(binding, "topology.nodes.start")
                    self._require_provider_capability(binding, "topology.nodes.state.read")
                    provider.start_node(binding["gns3_project_id"], node_id)
                    observed_node = provider.get_node_state(binding["gns3_project_id"], node_id)
                    if observed_node is None or str(observed_node.get("status", "")).lower() not in {"started", "running"}:
                        raise WiFiLabProvisioningError(
                            "GNS3 node lifecycle read-back did not confirm the requested started state"
                        )
                    operations["started_nodes"].append(item)

                after_nodes, after_links = self._observed_topology(provider, binding["gns3_project_id"])
                after = self.analyze_snapshot(
                    project_id=binding["gns3_project_id"],
                    project_status="opened",
                    nodes=after_nodes,
                    links=after_links,
                )
                if not after["can_apply"] or after["nodes_to_start"]:
                    raise WiFiLabProvisioningError(
                        "GNS3 provider state did not satisfy the Wi-Fi lab provisioning postconditions"
                    )
                now = self._now()
                with self.database.transaction(immediate=True) as connection:
                    connection.execute(
                        """INSERT INTO audit_events(
                           audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
                           ) VALUES(?,?,?,?,?,?,?)""",
                        (
                            "AUD-" + secrets.token_hex(12), actor, "WIFI_LAB_GNS3_PROVISIONED",
                            "LAB", str(lab_id),
                            json.dumps({
                                "project_id": binding["project_id"],
                                "gns3_project_id": binding["gns3_project_id"],
                                "started_nodes": operations["started_nodes"],
                                "created_management_link": operations["created_management_link"],
                            }, sort_keys=True, separators=(",", ":")),
                            now,
                        ),
                    )
                return {
                    "lab_id": lab_id, "project_id": binding["project_id"],
                    "gns3_project_id": binding["gns3_project_id"],
                    "status": "APPLIED", "operations": operations,
                    "reconciliation": after,
                }

            return self._with_provider(binding, actor, execute)
        except (WiFiLabProvisioningError, WiFiLabProvisioningNotFound):
            raise
        except Exception as exc:
            raise WiFiLabProvisioningError(
                "GNS3 provisioning stopped safely; inspect provider state before retrying"
            ) from exc
        finally:
            lease.release()
