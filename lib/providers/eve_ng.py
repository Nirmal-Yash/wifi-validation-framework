"""EVE-NG REST adapter; native lab paths, JSend envelopes and bridge networks are preserved."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from lib.providers.http import ProviderHTTPError, ProviderHTTPSession, validate_provider_endpoint


class EVENGProviderError(ProviderHTTPError):
    """Sanitized EVE-NG API failure."""


def _data(value):
    if isinstance(value, dict):
        return value.get("data", value)
    return value


def _rows(value):
    data = _data(value)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        rows = []
        for key, item in data.items():
            if not isinstance(item, dict):
                continue
            if any(field in item for field in ("id", "node_id", "link_id", "compute_id")):
                rows.append(item)
            else:
                rows.append({"id": str(key), **item})
        return rows
    return []


class EVENGProvider:
    provider_id = "eve-ng"
    MAX_FOLDER_DISCOVERY = 256
    MAX_LABS = 1000

    def __init__(self, endpoint_url, username, password, *, session_factory=None):
        self.endpoint_url = validate_provider_endpoint(endpoint_url)
        if not isinstance(username, str) or not username.strip() or len(username) > 128:
            raise EVENGProviderError("the linked EVE-NG credential has no usable username")
        if not isinstance(password, str) or not password:
            raise EVENGProviderError("the linked EVE-NG credential is unavailable")
        self.username = username
        self._password = password
        self._http = ProviderHTTPSession(self.endpoint_url, session_factory=session_factory)
        self._connected = False
        self._version = {}
        self._auth = {}

    @staticmethod
    def _folder_path(value, name="folder_path"):
        if not isinstance(value, str) or not value.strip() or len(value) > 512:
            raise EVENGProviderError(f"{name} is invalid")
        item = value.strip()
        if not item.startswith("/") or "\\" in item or "\x00" in item:
            raise EVENGProviderError(f"{name} must be an absolute EVE-NG folder path")
        parts = [part for part in item.split("/") if part]
        if any(part in {".", ".."} for part in parts):
            raise EVENGProviderError(f"{name} contains an unsafe path component")
        return "/" + "/".join(parts) if parts else "/"

    @classmethod
    def _path(cls, value, name="lab_path"):
        item = cls._folder_path(value, name)
        parts = [part for part in item.split("/") if part]
        if not parts or parts[-1].lower().endswith(".unl") is False:
            raise EVENGProviderError(f"{name} must identify an EVE-NG .unl lab")
        return item

    @staticmethod
    def _segment(value, name):
        item = str(value or "").strip()
        if not item or len(item) > 128 or any(ord(ch) < 33 for ch in item) or "/" in item or "\\" in item:
            raise EVENGProviderError(f"{name} is invalid")
        return quote(item, safe="")

    @staticmethod
    def _api_path(path):
        return quote(path, safe="/")

    def _request(self, method, path, *, payload=None, allow_fail=False):
        try:
            result = self._http.request(method, path, payload=payload,
                                        headers={"Content-Type": "application/json"})
        except ProviderHTTPError as exc:
            if allow_fail and "HTTP 404" in str(exc):
                return None
            raise EVENGProviderError(str(exc)) from exc
        if result is None:
            return None
        if isinstance(result, dict):
            status = str(result.get("status") or "").lower()
            code = result.get("code")
            if status in {"unauthorized", "forbidden", "fail", "error"} or (
                isinstance(code, int) and code >= 400
            ):
                if allow_fail and code == 404:
                    return None
                raise EVENGProviderError("EVE-NG API rejected " + method.upper() + " " + path.split("?")[0])
        return result

    def connect(self):
        payload = {"username": self.username, "password": self._password}
        if self.endpoint_url.startswith("https://"):
            payload["html5"] = "0"
        self._request("POST", "/api/auth/login", payload=payload)
        self._auth = _data(self._request("GET", "/api/auth"))
        status = _data(self._request("GET", "/api/status"))
        if not isinstance(self._auth, dict) or not isinstance(status, dict):
            raise EVENGProviderError("EVE-NG login verification returned an invalid response")
        self._version = {
            key: status[key] for key in ("version", "qemu_version", "edition")
            if isinstance(status.get(key), (str, int, float))
        }
        # Edition is intentionally UNKNOWN unless the controller reports it explicitly.
        self._version["edition"] = str(status.get("edition") or "UNKNOWN").upper()
        self._connected = True
        return {"connected": True, "status": "HEALTHY", "provider_id": self.provider_id,
                "version": dict(self._version), "edition": self._version["edition"],
                "observed_at": datetime.now(timezone.utc).isoformat()}

    def disconnect(self):
        try:
            if self._http is not None and not self._http.closed:
                try:
                    self._request("GET", "/api/auth/logout", allow_fail=True)
                except Exception:
                    # Logout is best effort; the local cookie jar is always destroyed.
                    pass
        finally:
            self._connected = False
            self._password = ""
            if self._http is not None:
                self._http.close()

    def health_check(self):
        if not self._connected:
            raise EVENGProviderError("EVE-NG session is not authenticated")
        status = _data(self._request("GET", "/api/status"))
        if not isinstance(status, dict):
            raise EVENGProviderError("EVE-NG system status response is invalid")
        return {"status": "HEALTHY", "version": self.version(),
                "observed_at": datetime.now(timezone.utc).isoformat()}

    def version(self):
        return dict(self._version)

    def get_capabilities(self):
        from lib.providers.registry import DEFAULT_CAPABILITIES
        return [item.as_dict() for item in DEFAULT_CAPABILITIES if item.capability_id != "packet_capture.supported"]

    def list_projects(self):
        root = self._auth.get("folder") if isinstance(self._auth, dict) else "/"
        root = self._folder_path(root if isinstance(root, str) else "/")
        queue = [root]
        visited, result = set(), []
        while queue and len(visited) < self.MAX_FOLDER_DISCOVERY and len(result) < self.MAX_LABS:
            folder = queue.pop(0)
            if folder in visited:
                continue
            visited.add(folder)
            api_folder = "/api/folders" + ("" if folder == "/" else self._api_path(folder))
            listing = _data(self._request("GET", api_folder))
            if not isinstance(listing, dict):
                continue
            for raw in listing.get("labs", []) if isinstance(listing.get("labs"), list) else []:
                if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
                    continue
                path = self._path(raw["path"])
                result.append({"project_id": path, "name": str(raw.get("file") or path.rsplit("/", 1)[-1])[:120],
                               "status": "AVAILABLE"})
                if len(result) >= self.MAX_LABS:
                    break
            for raw in listing.get("folders", []) if isinstance(listing.get("folders"), list) else []:
                if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
                    continue
                try:
                    path = self._folder_path(raw["path"])
                except EVENGProviderError:
                    continue
                if path in {"/", folder}:
                    continue
                queue.append(path)
        return result

    def create_lab(self, name, *, scene_width=1600, scene_height=900):
        if not isinstance(name, str) or not name.strip() or len(name) > 120 or "/" in name or "\\" in name:
            raise EVENGProviderError("EVE-NG lab name is invalid")
        root = self._auth.get("folder") if isinstance(self._auth, dict) else "/"
        folder = self._folder_path(root if isinstance(root, str) else "/")
        lab_path = folder.rstrip("/") + "/" + name.strip() + ".unl"
        payload = {"path": folder, "name": name.strip(), "version": "1",
                   "author": "NetRegress", "description": "Created by NetRegress", "body": ""}
        self._request("POST", "/api/labs", payload=payload)
        # EVE-NG create-lab returns only a status message; verify the new
        # workspace through its native GET endpoint before reporting success.
        detail = _data(self._request("GET", "/api/labs" + self._api_path(lab_path)))
        if not isinstance(detail, dict):
            raise EVENGProviderError("EVE-NG did not expose the created lab after the create request")
        return {"project_id": lab_path, "lab_id": lab_path,
                "name": str(detail.get("name") or name.strip())}

    def delete_lab(self, project_id):
        path = self._path(project_id)
        self._request("DELETE", "/api/labs" + self._api_path(path))
        return {"project_id": path, "deleted": True}

    def list_templates(self):
        value = _data(self._request("GET", "/api/list/templates/"))
        result = []
        if not isinstance(value, dict):
            raise EVENGProviderError("EVE-NG template catalogue is invalid")
        for template_id, label in value.items():
            if not isinstance(template_id, str) or not template_id:
                continue
            missing = isinstance(label, str) and label.lower().endswith(".missing")
            result.append({
                "template_id": template_id, "name": str(label)[:120],
                "category": "node", "template_type": "eve-ng",
                "compute_id": "eve-ng", "image_status": "MISSING" if missing else "UNKNOWN",
            })
        return result

    def get_resource_availability(self):
        status = _data(self._request("GET", "/api/status"))
        if not isinstance(status, dict):
            raise EVENGProviderError("EVE-NG resource status is invalid")
        compute = {"compute_id": "eve-ng", "name": "EVE-NG server", "connected": True}
        for field, key in (("cpu_cores_total", "cpu"), ("memory_gb_total", "mem")):
            raw = status.get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0:
                compute[field] = raw
        return {"computes": [compute], "observed_at": datetime.now(timezone.utc).isoformat()}

    def get_template_image_availability(self, template_id):
        template = self._segment(template_id, "template_id")
        value = _data(self._request("GET", f"/api/list/templates/{template}", allow_fail=True))
        if not isinstance(value, dict):
            return {"template_id": template_id, "status": "UNKNOWN", "required_images": [],
                    "available_images": [], "missing_images": [],
                    "reason": "EVE-NG did not expose the selected template detail"}
        options = value.get("options") if isinstance(value.get("options"), dict) else {}
        image = options.get("image") if isinstance(options.get("image"), dict) else {}
        image_list = image.get("list") if isinstance(image.get("list"), dict) else {}
        candidates = sorted(str(key) for key in image_list)
        missing = [item for item in candidates if item.lower().endswith(".missing")]
        available = [item for item in candidates if item not in missing]
        status = "MISSING" if candidates and not available else "AVAILABLE" if available else "UNKNOWN"
        return {"template_id": template_id, "status": status,
                "required_images": candidates, "available_images": available,
                "missing_images": missing,
                "reason": None if status != "UNKNOWN" else "EVE-NG did not report image catalogue entries",
                "observed_at": datetime.now(timezone.utc).isoformat()}

    def _lab(self, project_id):
        return self._api_path(self._path(project_id))

    def _nodes_raw(self, project_id):
        return _rows(self._request("GET", "/api/labs" + self._lab(project_id) + "/nodes"))

    @staticmethod
    def _state(value):
        if value == 0 or str(value).lower() in {"0", "stopped", "stop"}:
            return "STOPPED"
        if value == 1 or str(value).lower() in {"1", "building", "starting"}:
            return "BUILDING"
        if value == 2 or str(value).lower() in {"2", "started", "running"}:
            return "STARTED"
        return "UNKNOWN"

    def list_nodes(self, project_id):
        result = []
        for item in self._nodes_raw(project_id):
            node_id = item.get("id")
            if node_id is None:
                continue
            ports = self.get_interfaces(project_id, str(node_id))
            result.append({
                "node_id": str(node_id), "name": str(item.get("name") or node_id)[:120],
                "template_id": item.get("template"), "status": self._state(item.get("status")),
                "ports": ports, "image": item.get("image"),
            })
        return result

    def _topology_raw(self, project_id):
        value = _data(self._request("GET", "/api/labs" + self._lab(project_id) + "/topology"))
        if not isinstance(value, list):
            raise EVENGProviderError("EVE-NG topology response is invalid")
        return value

    def _network_rows(self, project_id):
        return _rows(self._request("GET", "/api/labs" + self._lab(project_id) + "/networks"))

    def list_links(self, project_id):
        edges = self._topology_raw(project_id)
        attached = {}
        direct = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            media = str(edge.get("type") or "ethernet").lower()
            if media not in {"ethernet", "serial"}:
                continue
            source_type, target_type = edge.get("source_type"), edge.get("destination_type")
            source, target = edge.get("source"), edge.get("destination")
            adapter = 1 if media == "serial" else 0
            if media == "ethernet" and source_type == "node" and target_type == "network":
                attached.setdefault(str(target), []).append((str(source), str(edge.get("source_label") or ""), adapter))
            elif media == "ethernet" and source_type == "network" and target_type == "node":
                attached.setdefault(str(source), []).append((str(target), str(edge.get("destination_label") or ""), adapter))
            elif source_type == "node" and target_type == "node":
                direct.append((source, target, edge.get("source_label"), edge.get("destination_label"), media, adapter))
        network_rows = self._network_rows(project_id)
        id_map = {str(item.get("id")): item for item in network_rows if item.get("id") is not None}
        result = []
        for network_key, peers in attached.items():
            if len(peers) != 2:
                continue
            network_id = network_key.replace("network", "", 1)
            if not network_id.isdigit():
                continue
            left, right = peers
            left_node, right_node = left[0].replace("node", "", 1), right[0].replace("node", "", 1)
            if not left_node.isdigit() or not right_node.isdigit():
                continue
            result.append({"link_id": network_id, "nodes": [
                {"node_id": left_node, "adapter_number": left[2], "port_number": self._port_number(left[1])},
                {"node_id": right_node, "adapter_number": right[2], "port_number": self._port_number(right[1])},
            ], "network_name": id_map.get(network_id, {}).get("name")})
        for source, target, source_label, target_label, media, adapter in direct:
            s_id, t_id = str(source).replace("node", "", 1), str(target).replace("node", "", 1)
            if s_id.isdigit() and t_id.isdigit():
                link_id = "direct-" + media + "-" + s_id + "-" + t_id
                result.append({"link_id": link_id, "nodes": [
                    {"node_id": s_id, "adapter_number": adapter, "port_number": self._port_number(source_label)},
                    {"node_id": t_id, "adapter_number": adapter, "port_number": self._port_number(target_label)},
                ]})
        return result

    @staticmethod
    def _port_number(label):
        import re
        text = str(label or "")
        match = re.search(r"(\d+)\s*$", text)
        return int(match.group(1)) if match else 0

    def create_node(self, project_id, template_id, *, name, x, y):
        lab, template = self._lab(project_id), self._segment(template_id, "template_id")
        detail = _data(self._request("GET", f"/api/list/templates/{template}"))
        if not isinstance(detail, dict):
            raise EVENGProviderError("EVE-NG template detail is unavailable")
        options = detail.get("options") if isinstance(detail.get("options"), dict) else {}
        def option_value(key):
            entry = options.get(key)
            return entry.get("value") if isinstance(entry, dict) else None
        image = option_value("image")
        image_options = options.get("image") if isinstance(options.get("image"), dict) else {}
        image_list = image_options.get("list") if isinstance(image_options.get("list"), dict) else {}
        available_images = [
            str(key) for key in image_list
            if isinstance(key, str) and key and not key.lower().endswith(".missing")
        ]
        if not available_images:
            raise EVENGProviderError("EVE-NG template has no verified installed image choice")
        if not isinstance(image, str) or image not in image_list or image.lower().endswith(".missing"):
            image = available_images[0]
        if image not in available_images:
            raise EVENGProviderError("selected EVE-NG template image is not present in the installed image catalogue")
        node_type = str(detail.get("type") or "qemu").lower()
        if node_type not in {"qemu", "iol", "dynamips"}:
            raise EVENGProviderError("EVE-NG template uses an unsupported native node type")
        payload = {
            "type": node_type, "template": template, "config": option_value("config") or "Unconfigured",
            "delay": option_value("delay") if isinstance(option_value("delay"), int) else 0,
            "icon": option_value("icon") or "Router.png", "image": image,
            "name": str(name)[:120],
            "left": f"{max(0, min(100, round(float(x) / 100)))}%",
            "top": f"{max(0, min(100, round(float(y) / 100)))}%",
            "console": option_value("console") or "telnet",
        }
        for key in ("ram", "cpu", "ethernet", "serial", "nvram"):
            value = option_value(key)
            if isinstance(value, (int, str)) and str(value).isdigit():
                payload[key] = int(value)
        result = _data(self._request("POST", f"/api/labs{lab}/nodes", payload=payload))
        node_id = result.get("id") if isinstance(result, dict) else None
        if node_id is None:
            nodes = self._nodes_raw(project_id)
            match = next((item for item in nodes if item.get("name") == name and item.get("template") == template_id), None)
            node_id = match.get("id") if match else None
        if node_id is None:
            raise EVENGProviderError("EVE-NG did not return an observable node identifier after creation")
        return {"node_id": str(node_id), "name": name, "template_id": template_id}

    def delete_node(self, project_id, node_id):
        lab, node = self._lab(project_id), self._segment(node_id, "node_id")
        self._request("DELETE", f"/api/labs{lab}/nodes/{node}")
        return {"project_id": project_id, "node_id": node_id, "deleted": True}

    def get_node_state(self, project_id, node_id):
        lab, node = self._lab(project_id), self._segment(node_id, "node_id")
        value = _data(self._request("GET", f"/api/labs{lab}/nodes/{node}"))
        if not isinstance(value, dict):
            raise EVENGProviderError("EVE-NG node state response is invalid")
        return {"node_id": str(node_id), "name": str(value.get("name") or node_id),
                "template_id": value.get("template"), "status": self._state(value.get("status"))}

    def _node_action(self, project_id, node_id, action):
        lab, node = self._lab(project_id), self._segment(node_id, "node_id")
        self._request("GET", f"/api/labs{lab}/nodes/{node}/{action}")
        return self.get_node_state(project_id, node_id)

    def start_node(self, project_id, node_id):
        return self._node_action(project_id, node_id, "start")

    def stop_node(self, project_id, node_id):
        return self._node_action(project_id, node_id, "stop")

    def get_interfaces(self, project_id, node_id):
        lab, node = self._lab(project_id), self._segment(node_id, "node_id")
        value = _data(self._request("GET", f"/api/labs{lab}/nodes/{node}/interfaces"))
        if not isinstance(value, dict):
            raise EVENGProviderError("EVE-NG node interface response is invalid")
        result = []
        for index, item in enumerate(value.get("ethernet", []) if isinstance(value.get("ethernet"), list) else []):
            if isinstance(item, dict):
                name = str(item.get("name") or f"eth{index}")
                result.append({"adapter_number": 0, "port_number": index, "name": name, "short_name": name, "link_type": "ethernet"})
        for index, item in enumerate(value.get("serial", []) if isinstance(value.get("serial"), list) else []):
            if isinstance(item, dict):
                name = str(item.get("name") or f"serial{index}")
                result.append({"adapter_number": 1, "port_number": index, "name": name, "short_name": name, "link_type": "serial"})
        return result

    def create_link(self, project_id, *, source_node_id, source_adapter, source_port,
                    target_node_id, target_adapter, target_port):
        if source_adapter != 0 or target_adapter != 0:
            raise EVENGProviderError("EVE-NG adapter currently creates native bridge links for Ethernet interfaces only; serial link creation is unsupported")
        left = next((item for item in self.get_interfaces(project_id, source_node_id)
                     if item["adapter_number"] == source_adapter and item["port_number"] == source_port), None)
        right = next((item for item in self.get_interfaces(project_id, target_node_id)
                      if item["adapter_number"] == target_adapter and item["port_number"] == target_port), None)
        if left is None or right is None:
            raise EVENGProviderError("EVE-NG link endpoint does not match an observed interface")
        lab = self._lab(project_id)
        name = ("NR-" + str(source_node_id) + "-" + str(target_node_id) + "-" +
                str(source_adapter) + "-" + str(source_port) + "-" + str(target_adapter) + "-" + str(target_port))[:120]
        result = _data(self._request("POST", f"/api/labs{lab}/networks", payload={
            "type": "bridge", "name": name, "visibility": 1, "left": "50%", "top": "50%",
        }))
        network_id = result.get("id") if isinstance(result, dict) else None
        if network_id is None:
            raise EVENGProviderError("EVE-NG did not return a bridge network ID for the requested link")
        attached = []
        try:
            for node_id, interface in ((source_node_id, left), (target_node_id, right)):
                node = self._segment(node_id, "node_id")
                self._request("PUT", f"/api/labs{lab}/nodes/{node}/interfaces",
                              payload={interface["name"]: str(network_id)})
                attached.append((node, interface["name"]))
        except Exception:
            for node, interface_name in attached:
                try:
                    self._request("PUT", f"/api/labs{lab}/nodes/{node}/interfaces", payload={interface_name: "0"})
                except Exception:
                    pass
            try:
                self._request("DELETE", f"/api/labs{lab}/networks/{self._segment(network_id, 'network_id')}")
            except Exception:
                pass
            raise
        return {"link_id": str(network_id), "nodes": [
            {"node_id": str(source_node_id), "adapter_number": source_adapter, "port_number": source_port},
            {"node_id": str(target_node_id), "adapter_number": target_adapter, "port_number": target_port},
        ]}

    def delete_link(self, project_id, link_id):
        if str(link_id).startswith("direct-"):
            raise EVENGProviderError("EVE-NG direct node links are observed-only and cannot be safely removed by the network API")
        lab, network = self._lab(project_id), self._segment(link_id, "network_id")
        self._request("DELETE", f"/api/labs{lab}/networks/{network}")
        return {"project_id": project_id, "link_id": link_id, "deleted": True}

    def get_observed_topology(self, project_id):
        nodes = self.list_nodes(project_id)
        links = self.list_links(project_id)
        return {"project_id": project_id, "nodes": nodes, "links": links}

    def capture_support(self):
        return {"supported": False, "scope": "none",
                "reason": "EVE-NG packet capture is not enabled by the common controller API adapter"}
