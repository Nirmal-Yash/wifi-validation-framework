"""Cisco Modeling Labs REST adapter for the shared NetRegress provider contract.

The adapter uses the public CML REST API. Server-reported image, compute and
licensing data are observations; CML-Free limits are never embedded as constants.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from lib.providers.http import ProviderHTTPError, ProviderHTTPSession, validate_provider_endpoint


class CMLProviderError(ProviderHTTPError):
    """Sanitized Cisco Modeling Labs API failure."""


def _items(value):
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        data = value.get("data", value)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [item for item in data.values() if isinstance(item, dict)]
    return []


def _id(value, *keys):
    for key in keys:
        item = value.get(key)
        if isinstance(item, (str, int)) and not isinstance(item, bool) and str(item).strip():
            return str(item).strip()
    return None


class CMLProvider:
    provider_id = "cml"

    def __init__(self, endpoint_url, username, password, *, session_factory=None):
        self.endpoint_url = validate_provider_endpoint(endpoint_url)
        if not isinstance(username, str) or not username.strip() or len(username) > 128:
            raise CMLProviderError("the linked CML credential has no usable username")
        if not isinstance(password, str) or not password:
            raise CMLProviderError("the linked CML credential is unavailable")
        self.username = username
        self._password = password
        self._session_factory = session_factory
        self._http = None
        self._connected = False
        self._version = {}

    @staticmethod
    def _segment(value, name):
        item = str(value or "").strip()
        if not item or len(item) > 256 or any(ord(ch) < 33 for ch in item):
            raise CMLProviderError(f"{name} is invalid")
        return quote(item, safe="")

    def _request(self, method, path, *, payload=None, params=None):
        if self._http is None:
            self._http = ProviderHTTPSession(self.endpoint_url, session_factory=self._session_factory)
        try:
            return self._http.request(method, path, payload=payload, params=params)
        except ProviderHTTPError as exc:
            raise CMLProviderError(str(exc)) from exc

    @staticmethod
    def _data(value):
        if isinstance(value, dict) and "data" in value:
            return value["data"]
        return value

    def connect(self):
        result = self._request(
            "POST", "/api/v0/authenticate",
            payload={"username": self.username, "password": self._password},
        )
        token = result
        if isinstance(result, dict):
            token = result.get("token") or result.get("id")
            nested = result.get("data")
            if not token and isinstance(nested, dict):
                token = nested.get("token") or nested.get("id")
        if isinstance(token, str) and token:
            self._http.session.headers.update({"Authorization": "Bearer " + token})
        authentication = self._request("GET", "/api/v0/authentication")
        if not isinstance(authentication, (dict, list)):
            raise CMLProviderError("CML authentication verification returned an invalid response")
        self._connected = True
        self._version = self.version()
        return {"connected": True, "status": "HEALTHY", "provider_id": self.provider_id,
                "version": self._version, "observed_at": datetime.now(timezone.utc).isoformat()}

    def disconnect(self):
        self._connected = False
        if self._http is not None:
            self._http.close()
            self._http = None
        self._password = ""

    def health_check(self):
        if not self._connected:
            raise CMLProviderError("CML session is not authenticated")
        system = self._data(self._request("GET", "/api/v0/system_information"))
        if not isinstance(system, dict):
            raise CMLProviderError("CML system information response is invalid")
        return {"status": "HEALTHY", "version": self.version(), "observed_at": datetime.now(timezone.utc).isoformat()}

    def version(self):
        if self._version:
            return dict(self._version)
        value = self._data(self._request("GET", "/api/v0/system_information"))
        if not isinstance(value, dict):
            raise CMLProviderError("CML version information is invalid")
        self._version = {
            key: value[key] for key in ("version", "release", "build", "hostname", "edition")
            if isinstance(value.get(key), (str, int, float))
        }
        if not self._version.get("version") and self._version.get("release"):
            self._version["version"] = self._version["release"]
        return dict(self._version)

    def get_capabilities(self):
        from lib.providers.registry import DEFAULT_CAPABILITIES
        return [
            item.as_dict() for item in DEFAULT_CAPABILITIES
            if item.capability_id != "packet_capture.supported"
        ]

    def list_projects(self):
        value = self._data(self._request("GET", "/api/v0/labs", params={"with_data": "false"}))
        rows = []
        for item in _items(value):
            workspace_id = _id(item, "id", "lab_id")
            if not workspace_id:
                continue
            rows.append({
                "project_id": workspace_id,
                "name": str(item.get("lab_title") or item.get("title") or item.get("name") or workspace_id)[:120],
                "status": str(item.get("state") or item.get("status") or "UNKNOWN").upper(),
            })
        return rows

    def create_lab(self, name, *, scene_width=1600, scene_height=900):
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise CMLProviderError("CML lab name must contain 1 to 120 characters")
        value = self._data(self._request("POST", "/api/v0/labs", payload={
            "lab_title": name.strip(), "lab_description": "Created by NetRegress",
        }))
        if isinstance(value, str):
            workspace_id = value
        elif isinstance(value, dict):
            workspace_id = _id(value, "id", "lab_id")
        else:
            workspace_id = None
        if not workspace_id:
            raise CMLProviderError("CML did not return a lab identifier after creation")
        return {"project_id": workspace_id, "lab_id": workspace_id, "name": name.strip()}

    def delete_lab(self, project_id):
        lab = self._segment(project_id, "lab_id")
        self._request("DELETE", f"/api/v0/labs/{lab}")
        return {"project_id": project_id, "deleted": True}

    def list_templates(self):
        definitions = _items(self._data(self._request("GET", "/api/v0/node_definitions")))
        result = []
        for item in definitions:
            definition_id = _id(item, "id", "node_definition", "node_definition_id")
            if not definition_id:
                continue
            result.append({
                "template_id": definition_id,
                "name": str(item.get("description") or item.get("label") or item.get("id") or definition_id)[:120],
                "category": str(item.get("device_type") or item.get("group") or "node"),
                "template_type": str(item.get("device_type") or item.get("sim_type") or "cml"),
                "compute_id": str(item["compute_id"]) if isinstance(item.get("compute_id"), str) and item["compute_id"] else None,
                "image_definition_ids": item.get("image_definitions") if isinstance(item.get("image_definitions"), list) else [],
                "resource_requirements": {
                    key: item[key] for key in ("ram", "cpus", "cpu_limit", "data_volume")
                    if isinstance(item.get(key), (int, float, str))
                },
            })
        return result

    @staticmethod
    def _is_restricted(exc):
        return any(code in str(exc) for code in ("HTTP 401", "HTTP 403"))

    def get_resource_availability(self):
        observed_at = datetime.now(timezone.utc).isoformat()
        try:
            value = self._data(self._request("GET", "/api/v0/system/compute_hosts"))
            computes = []
            for item in _items(value):
                compute_id = _id(item, "id", "compute_id")
                if not compute_id:
                    continue
                state = str(item.get("state") or item.get("status") or "").upper()
                computes.append({
                    "compute_id": compute_id,
                    "name": str(item.get("name") or item.get("hostname") or compute_id)[:120],
                    "connected": state in {"READY", "ONLINE", "CONNECTED"} if state else None,
                    "state": state or "UNKNOWN",
                })
            compute_status = "OBSERVED"
        except CMLProviderError as exc:
            if not self._is_restricted(exc):
                raise
            computes, compute_status = [], "RESTRICTED"
        try:
            licensing = self._data(self._request("GET", "/api/v0/licensing"))
            license_summary = {}
            if isinstance(licensing, dict):
                for key in ("status", "authorization_status", "product", "features", "quotas"):
                    if key in licensing and isinstance(licensing[key], (str, int, float, bool, list, dict)):
                        license_summary[key] = licensing[key]
            license_status = "OBSERVED" if license_summary else "UNKNOWN"
        except CMLProviderError as exc:
            if not self._is_restricted(exc):
                raise
            license_summary, license_status = {}, "RESTRICTED"
        return {"computes": computes, "compute_observation": compute_status,
                "licensing": license_summary, "licensing_observation": license_status,
                "observed_at": observed_at}

    def get_template_image_availability(self, template_id):
        template = self._segment(template_id, "node_definition_id")
        observed_at = datetime.now(timezone.utc).isoformat()
        try:
            value = self._data(self._request("GET", f"/api/v0/node_definitions/{template}/image_definitions"))
        except CMLProviderError as exc:
            if not (self._is_restricted(exc) or "HTTP 404" in str(exc)):
                raise
            return {"template_id": template_id, "status": "UNKNOWN", "required_images": [],
                    "available_images": [], "missing_images": [],
                    "reason": "CML image-definition details are unavailable to this credential or API version",
                    "observed_at": observed_at}
        images = _items(value)
        ids = sorted({_id(item, "id", "image_definition_id") for item in images if _id(item, "id", "image_definition_id")})
        ready = []
        missing = []
        for item in images:
            image_id = _id(item, "id", "image_definition_id")
            state = str(item.get("state") or item.get("status") or "").upper()
            installed = item.get("installed") is True or item.get("is_installed") is True
            explicitly_missing = item.get("installed") is False or item.get("is_installed") is False or state in {"MISSING", "UNAVAILABLE"}
            if image_id and installed:
                ready.append(image_id)
            elif image_id and explicitly_missing:
                missing.append(image_id)
        status = "MISSING" if ids and len(missing) == len(ids) else "AVAILABLE" if ids and len(ready) == len(ids) else "UNKNOWN"
        reason = None if status in {"AVAILABLE", "MISSING"} else (
            "CML returned image-definition associations but did not explicitly report installed image readiness"
            if ids else "CML returned no image-definition records; installed image availability is not inferred"
        )
        return {"template_id": template_id, "status": status, "required_images": ids,
                "available_images": sorted(ready), "missing_images": sorted(missing),
                "image_definitions_registered": ids, "reason": reason, "observed_at": observed_at}

    def _lab_path(self, project_id):
        return self._segment(project_id, "lab_id")

    def _node_path(self, node_id):
        return self._segment(node_id, "node_id")

    @staticmethod
    def _node(item):
        if not isinstance(item, dict):
            return None
        node_id = _id(item, "id", "node_id")
        if not node_id:
            return None
        operational = item.get("operational") if isinstance(item.get("operational"), dict) else {}
        raw_state = item.get("state") or operational.get("state") or "UNKNOWN"
        state = str(raw_state).upper()
        if state in {"BOOTED", "STARTING", "BOOTING"}:
            state = "STARTED" if state == "BOOTED" else "STARTING"
        ports = item.get("interfaces") if isinstance(item.get("interfaces"), list) else []
        return {
            "node_id": node_id, "name": str(item.get("label") or item.get("name") or node_id)[:120],
            "template_id": _id(item, "node_definition", "node_definition_id", "template_id"),
            "status": state,
            "x": item.get("x"), "y": item.get("y"),
            "ports": [
                {"adapter_number": int(port.get("adapter_number", 0) or 0),
                 "port_number": int(port.get("port_number", index) or 0),
                 "name": str(port.get("label") or port.get("name") or f"eth{index}")}
                for index, port in enumerate(ports) if isinstance(port, dict)
            ],
        }

    def list_nodes(self, project_id):
        lab = self._lab_path(project_id)
        return [node for node in (self._node(item) for item in _items(self._data(
            self._request("GET", f"/api/v0/labs/{lab}/nodes")
        ))) if node]

    def list_links(self, project_id):
        lab = self._lab_path(project_id)
        return [link for link in (self._link(item) for item in _items(self._data(
            self._request("GET", f"/api/v0/labs/{lab}/links")
        ))) if link]

    @staticmethod
    def _link(item):
        if not isinstance(item, dict):
            return None
        link_id = _id(item, "id", "link_id")
        if not link_id:
            return None
        endpoints = []
        for side in ("n1", "n2"):
            node_id = _id(item, side, side + "_node_id")
            interface_id = _id(item, "i1" if side == "n1" else "i2", side + "_interface_id")
            if node_id:
                endpoints.append({"node_id": node_id, "adapter_number": 0, "port_number": int(interface_id) if interface_id and interface_id.isdigit() else 0})
        return {"link_id": link_id, "nodes": endpoints}

    def create_node(self, project_id, template_id, *, name, x, y):
        lab = self._lab_path(project_id)
        template = self._segment(template_id, "node_definition_id")
        result = self._data(self._request("POST", f"/api/v0/labs/{lab}/nodes", payload={
            "node_definition": template, "label": str(name)[:120], "x": x, "y": y,
        }))
        node_id = _id(result, "id", "node_id") if isinstance(result, dict) else None
        if not node_id:
            raise CMLProviderError("CML did not return a created node identifier")
        return {"node_id": node_id, "name": name, "template_id": template_id}

    def delete_node(self, project_id, node_id):
        lab, node = self._lab_path(project_id), self._node_path(node_id)
        self._request("DELETE", f"/api/v0/labs/{lab}/nodes/{node}")
        return {"project_id": project_id, "node_id": node_id, "deleted": True}

    def get_node_state(self, project_id, node_id):
        lab, node = self._lab_path(project_id), self._node_path(node_id)
        value = self._data(self._request("GET", f"/api/v0/labs/{lab}/nodes/{node}"))
        if not isinstance(value, dict):
            raise CMLProviderError("CML node-state response is invalid")
        normalized = self._node(value) or {"node_id": node_id}
        normalized["status"] = str((value.get("operational") or {}).get("state") or value.get("state") or "UNKNOWN").upper()
        if normalized["status"] == "BOOTED":
            normalized["status"] = "STARTED"
        return normalized

    def _set_node_state(self, project_id, node_id, state):
        lab, node = self._lab_path(project_id), self._node_path(node_id)
        self._request("PUT", f"/api/v0/labs/{lab}/nodes/{node}/state", payload={"state": state})
        return self.get_node_state(project_id, node_id)

    def start_node(self, project_id, node_id):
        return self._set_node_state(project_id, node_id, "STARTED")

    def stop_node(self, project_id, node_id):
        return self._set_node_state(project_id, node_id, "STOPPED")

    def get_interfaces(self, project_id, node_id):
        lab, node = self._lab_path(project_id), self._node_path(node_id)
        value = self._data(self._request("GET", f"/api/v0/labs/{lab}/nodes/{node}/interfaces"))
        rows = _items(value)
        if not rows and isinstance(value, dict):
            rows = [item for item in value.values() if isinstance(item, dict)]
        result = []
        for index, item in enumerate(rows):
            raw_port = item.get("id", item.get("port", index))
            try:
                port = int(raw_port)
            except (TypeError, ValueError):
                port = index
            try:
                adapter = int(item.get("adapter_number", 0) or 0)
            except (TypeError, ValueError):
                adapter = 0
            if not 0 <= adapter <= 255 or not 0 <= port <= 255:
                continue
            name = str(item.get("label") or item.get("name") or f"eth{index}")[:64]
            result.append({"adapter_number": adapter, "port_number": port,
                           "name": name, "short_name": name})
        return result

    def create_link(self, project_id, *, source_node_id, source_adapter, source_port,
                    target_node_id, target_adapter, target_port):
        lab = self._lab_path(project_id)
        source = self.get_interfaces(project_id, source_node_id)
        target = self.get_interfaces(project_id, target_node_id)
        def find(ports, adapter, port):
            return next((item for item in ports if item["adapter_number"] == adapter and item["port_number"] == port), None)
        left, right = find(source, source_adapter, source_port), find(target, target_adapter, target_port)
        if left is None or right is None:
            raise CMLProviderError("CML link endpoint does not match an observed provider interface")
        payload = {"n1": source_node_id, "i1": left["name"], "n2": target_node_id, "i2": right["name"]}
        result = self._data(self._request("POST", f"/api/v0/labs/{lab}/links", payload=payload))
        link_id = _id(result, "id", "link_id") if isinstance(result, dict) else None
        if not link_id:
            raise CMLProviderError("CML did not return a created link identifier")
        return {"link_id": link_id, "nodes": [
            {"node_id": source_node_id, "adapter_number": source_adapter, "port_number": source_port},
            {"node_id": target_node_id, "adapter_number": target_adapter, "port_number": target_port},
        ]}

    def delete_link(self, project_id, link_id):
        lab, link = self._lab_path(project_id), self._node_path(link_id)
        self._request("DELETE", f"/api/v0/labs/{lab}/links/{link}")
        return {"project_id": project_id, "link_id": link_id, "deleted": True}

    def get_observed_topology(self, project_id):
        lab = self._lab_path(project_id)
        value = self._data(self._request("GET", f"/api/v0/labs/{lab}/topology"))
        nodes = self.list_nodes(project_id)
        links = self.list_links(project_id)
        if isinstance(value, dict):
            raw_nodes = value.get("nodes")
            raw_links = value.get("links")
            if isinstance(raw_nodes, list):
                by_id = {item["node_id"]: item for item in nodes}
                for item in raw_nodes:
                    normalized = self._node(item)
                    if normalized:
                        by_id[normalized["node_id"]] = normalized
                nodes = list(by_id.values())
            if isinstance(raw_links, list):
                by_id = {item["link_id"]: item for item in links}
                for item in raw_links:
                    normalized = self._link(item)
                    if normalized:
                        by_id[normalized["link_id"]] = normalized
                links = list(by_id.values())
        return {"project_id": project_id, "nodes": nodes, "links": links}

    def capture_support(self):
        return {
            "supported": False, "scope": "none",
            "reason": "The CML packet-capture operation is not implemented by this adapter version.",
        }

