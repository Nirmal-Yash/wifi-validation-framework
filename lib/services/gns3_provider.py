"""Bounded GNS3 reference adapter implementing the shared ProviderAdapter contract."""
from __future__ import annotations

import ipaddress
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import requests


class GNS3ProviderError(RuntimeError):
    """A sanitized GNS3 transport or contract failure."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class GNS3Provider:
    provider_id = "gns3"
    MAX_RESPONSE_BYTES = 2 * 1024 * 1024
    TIMEOUT = (3.05, 20.0)

    def __init__(self, endpoint_url: str, username: str, password: str, *, session_factory=None):
        self.endpoint_url = self.validate_endpoint(endpoint_url)
        if not isinstance(username, str) or not username.strip() or len(username) > 128:
            raise GNS3ProviderError("the linked GNS3 credential has no usable username")
        if not isinstance(password, str) or not password:
            raise GNS3ProviderError("the linked GNS3 credential is unavailable")
        self._username = username
        self._password = password
        self._session_factory = session_factory or requests.Session
        # HTTP sessions are short-lived per operation; connect() does not retain sockets.
        self._connected = False

    @staticmethod
    def validate_endpoint(value: object, *, expected_host: str | None = None) -> str:
        if not isinstance(value, str) or not value or len(value) > 512:
            raise GNS3ProviderError("GNS3 endpoint must be a valid private HTTP(S) URL")
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise GNS3ProviderError("GNS3 endpoint is malformed") from exc
        if (
            parsed.scheme not in {"http", "https"} or not hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
        ):
            raise GNS3ProviderError("GNS3 endpoint must not contain credentials, path, query or fragment")
        local_name = hostname.lower() == "localhost"
        try:
            address = ipaddress.ip_address(hostname)
            allowed_address = address.is_private or address.is_loopback or address.is_link_local
            if address.is_multicast or address.is_unspecified or address.is_reserved or address.is_global:
                allowed_address = False
        except ValueError:
            address = None
            allowed_address = local_name
        if not allowed_address:
            raise GNS3ProviderError("GNS3 endpoint must resolve to an explicitly local or private address")
        if parsed.scheme == "http" and not local_name and not (address and address.is_loopback):
            raise GNS3ProviderError("remote private GNS3 endpoints require HTTPS")
        if port is not None and not 1 <= port <= 65535:
            raise GNS3ProviderError("GNS3 endpoint port is invalid")
        if expected_host:
            expected = str(expected_host).strip().strip("[]").lower()
            actual = hostname.strip("[]").lower()
            try:
                matches = ipaddress.ip_address(expected) == ipaddress.ip_address(actual)
            except ValueError:
                matches = expected == actual
            if not matches:
                raise GNS3ProviderError("GNS3 endpoint host must match the registered controller device")
        return value.rstrip("/")

    @staticmethod
    def _segment(value: object, name: str) -> str:
        item = str(value or "").strip()
        if not _IDENTIFIER.fullmatch(item):
            raise GNS3ProviderError(f"{name} is not a safe provider identifier")
        return quote(item, safe="")

    def _request(self, method: str, path: str, *, payload: dict | None = None):
        session = self._session_factory()
        session.trust_env = False
        try:
            response = session.request(
                method, self.endpoint_url + path,
                auth=(self._username, self._password), json=payload,
                headers={"Accept": "application/json"},
                timeout=self.TIMEOUT, verify=True, allow_redirects=False, stream=True,
            )
            try:
                status = int(response.status_code)
                if status < 200 or status >= 300:
                    raise GNS3ProviderError(
                        f"GNS3 Controller returned HTTP {status} for {method} {path.split('?')[0]}"
                    )
                pieces = []
                size = 0
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.MAX_RESPONSE_BYTES:
                        raise GNS3ProviderError("GNS3 Controller response exceeded the 2 MiB safety limit")
                    pieces.append(chunk)
                raw = b"".join(pieces)
                if not raw:
                    return None
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise GNS3ProviderError("GNS3 Controller returned an invalid JSON response") from exc
            finally:
                response.close()
        except GNS3ProviderError:
            raise
        except requests.RequestException as exc:
            raise GNS3ProviderError(
                "GNS3 Controller request failed (" + type(exc).__name__ + ")"
            ) from exc
        finally:
            session.close()

    def version(self) -> dict:
        value = self._request("GET", "/v2/version")
        if not isinstance(value, dict):
            raise GNS3ProviderError("GNS3 Controller version response is invalid")
        return {key: value[key] for key in ("version", "local", "capabilities") if key in value}

    def list_projects(self) -> list[dict]:
        value = self._request("GET", "/v2/projects")
        if not isinstance(value, list):
            raise GNS3ProviderError("GNS3 project catalogue is invalid")
        return [
            {key: item[key] for key in ("project_id", "name", "status", "scene_width", "scene_height") if key in item}
            for item in value if isinstance(item, dict)
        ]

    def list_templates(self) -> list[dict]:
        value = self._request("GET", "/v2/templates")
        if not isinstance(value, list):
            raise GNS3ProviderError("GNS3 template catalogue is invalid")
        allowed = (
            "template_id", "name", "category", "builtin", "template_type", "compute_id",
            "default_name_format", "symbol", "hda_disk_image", "hdb_disk_image",
            "hdc_disk_image", "hdd_disk_image", "cdrom_image", "kernel_image",
            "initrd", "bios_image", "image", "docker_image", "iou_path",
            "image_name", "ram", "cpus",
        )
        return [
            {key: item[key] for key in allowed if key in item}
            for item in value if isinstance(item, dict)
        ]

    def get_resource_availability(self) -> dict:
        """Return bounded controller observations for the registered compute pool."""
        value = self._request("GET", "/v2/computes")
        if not isinstance(value, list):
            raise GNS3ProviderError("GNS3 compute availability response is invalid")
        computes = []
        for item in value:
            if not isinstance(item, dict) or not isinstance(item.get("compute_id"), str):
                continue
            row = {
                "compute_id": item["compute_id"],
                "name": item.get("name") if isinstance(item.get("name"), str) else item["compute_id"],
                "connected": item.get("connected") if isinstance(item.get("connected"), bool) else None,
            }
            for field in ("cpu_usage_percent", "memory_usage_percent"):
                raw = item.get(field)
                row[field] = (
                    round(float(raw), 2)
                    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and 0 <= raw <= 100
                    else None
                )
            computes.append(row)
        return {
            "computes": computes,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_template_image_availability(self, template_id: str) -> dict:
        """Check declared image filenames against the assigned GNS3 compute catalogue."""
        template = self._segment(template_id, "template_id")
        value = self._request("GET", f"/v2/templates/{template}")
        if not isinstance(value, dict) or value.get("template_id") != template_id:
            raise GNS3ProviderError("GNS3 template detail response is invalid")
        observed_at = datetime.now(timezone.utc).isoformat()
        if value.get("builtin") is True:
            return {
                "template_id": template_id, "status": "NOT_REQUIRED",
                "required_images": [], "available_images": [], "missing_images": [],
                "observed_at": observed_at,
            }
        emulator_by_type = {
            "qemu": "qemu", "dynamips": "dynamips", "iou": "iou",
            "docker": "docker", "vmware": "vmware", "virtualbox": "virtualbox",
        }
        emulator = emulator_by_type.get(value.get("template_type"))
        required_images = sorted({
            item.strip() for key, item in value.items()
            if isinstance(item, str) and item.strip()
            and (key.endswith("_image") or key in {"image", "docker_image", "iou_path", "image_name"})
        })
        compute_id = value.get("compute_id")
        if not emulator or not required_images or not isinstance(compute_id, str) or not compute_id:
            return {
                "template_id": template_id, "status": "UNKNOWN",
                "compute_id": compute_id if isinstance(compute_id, str) else None,
                "required_images": required_images, "available_images": [],
                "missing_images": [],
                "reason": "GNS3 did not expose a supported compute and explicit image requirement for this template",
                "observed_at": observed_at,
            }
        compute = self._segment(compute_id, "compute_id")
        images = self._request("GET", f"/v2/computes/{compute}/{emulator}/images")
        if not isinstance(images, list):
            raise GNS3ProviderError("GNS3 compute image catalogue is invalid")
        available_names = set()
        for item in images:
            candidate = item if isinstance(item, str) else None
            if isinstance(item, dict):
                candidate = next(
                    (item[key] for key in ("filename", "name", "image", "path") if isinstance(item.get(key), str)),
                    None,
                )
            if isinstance(candidate, str) and candidate.strip():
                available_names.add(candidate.strip().replace("\\\\", "/").rsplit("/", 1)[-1].casefold())
        available = [
            image for image in required_images
            if image.replace("\\\\", "/").rsplit("/", 1)[-1].casefold() in available_names
        ]
        missing = [image for image in required_images if image not in available]
        return {
            "template_id": template_id, "compute_id": compute_id,
            "status": "AVAILABLE" if not missing else "MISSING",
            "required_images": required_images, "available_images": available,
            "missing_images": missing, "observed_at": observed_at,
        }

    def list_nodes(self, project_id: str) -> list[dict]:
        project = self._segment(project_id, "project_id")
        value = self._request("GET", f"/v2/projects/{project}/nodes")
        if not isinstance(value, list):
            raise GNS3ProviderError("GNS3 node inventory is invalid")
        allowed = ("node_id", "name", "node_type", "status", "template_id", "x", "y", "compute_id", "ports")
        result = []
        for item in value:
            if not isinstance(item, dict):
                continue
            row = {key: item[key] for key in allowed if key in item}
            ports = item.get("ports")
            if isinstance(ports, list):
                row["ports"] = [
                    {key: port[key] for key in ("adapter_number", "port_number", "name", "short_name", "link_type") if key in port}
                    for port in ports if isinstance(port, dict)
                ]
            result.append(row)
        return result

    def list_links(self, project_id: str) -> list[dict]:
        project = self._segment(project_id, "project_id")
        value = self._request("GET", f"/v2/projects/{project}/links")
        if not isinstance(value, list):
            raise GNS3ProviderError("GNS3 link inventory is invalid")
        result = []
        for item in value:
            if not isinstance(item, dict):
                continue
            row = {key: item[key] for key in ("link_id", "link_type", "nodes", "suspend", "capturing") if key in item}
            nodes = item.get("nodes")
            if isinstance(nodes, list):
                row["nodes"] = [
                    {key: node[key] for key in ("node_id", "adapter_number", "port_number") if key in node}
                    for node in nodes if isinstance(node, dict)
                ]
            result.append(row)
        return result

    def create_node(self, project_id: str, template_id: str, *, name: str, x: float, y: float) -> dict:
        project = self._segment(project_id, "project_id")
        template = self._segment(template_id, "template_id")
        value = self._request(
            "POST", f"/v2/projects/{project}/templates/{template}",
            payload={"name": name, "x": x, "y": y},
        )
        if not isinstance(value, dict) or not isinstance(value.get("node_id"), str):
            raise GNS3ProviderError("GNS3 did not return a usable node identifier")
        return {
            key: value[key] for key in
            ("node_id", "name", "node_type", "status", "template_id", "ports", "x", "y")
            if key in value
        }

    def start_node(self, project_id: str, node_id: str):
        project = self._segment(project_id, "project_id")
        node = self._segment(node_id, "node_id")
        return self._request("POST", f"/v2/projects/{project}/nodes/{node}/start", payload={})

    def stop_node(self, project_id: str, node_id: str):
        project = self._segment(project_id, "project_id")
        node = self._segment(node_id, "node_id")
        return self._request("POST", f"/v2/projects/{project}/nodes/{node}/stop", payload={})

    def create_link(self, project_id: str, *, source_node_id: str, source_adapter: int,
                    source_port: int, target_node_id: str, target_adapter: int,
                    target_port: int):
        project = self._segment(project_id, "project_id")
        source = self._segment(source_node_id, "node_id")
        target = self._segment(target_node_id, "node_id")
        payload = {"nodes": [
            {"node_id": source, "adapter_number": source_adapter, "port_number": source_port},
            {"node_id": target, "adapter_number": target_adapter, "port_number": target_port},
        ]}
        value = self._request("POST", f"/v2/projects/{project}/links", payload=payload)
        if value is not None and not isinstance(value, dict):
            raise GNS3ProviderError("GNS3 returned an invalid link creation response")
        return value or {}

    def connect(self) -> dict:
        """Verify the controller is reachable without retaining a long-lived session."""
        result = self.health_check()
        self._connected = True
        return {"connected": True, **result}

    def disconnect(self) -> None:
        """Close the logical provider session; HTTP sessions are closed per request."""
        self._connected = False

    def health_check(self) -> dict:
        """Return a fresh authenticated controller observation or raise a typed error."""
        version = self.version()
        return {
            "status": "HEALTHY",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "version": version,
        }

    def get_capabilities(self) -> list[dict]:
        """Expose only the operations this reference adapter implements."""
        from lib.providers.registry import DEFAULT_CAPABILITIES
        return [item.as_dict() for item in DEFAULT_CAPABILITIES]

    def create_lab(
        self, name: str, *, scene_width: int = 1600, scene_height: int = 900,
    ) -> dict:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise GNS3ProviderError("lab name must contain 1 to 120 characters")
        if (
            type(scene_width) is not int or type(scene_height) is not int
            or not 100 <= scene_width <= 10000 or not 100 <= scene_height <= 10000
        ):
            raise GNS3ProviderError("lab canvas dimensions must be integers between 100 and 10000")
        value = self._request(
            "POST", "/v2/projects",
            payload={
                "name": name.strip(),
                "scene_width": scene_width,
                "scene_height": scene_height,
            },
        )
        if not isinstance(value, dict) or not isinstance(value.get("project_id"), str):
            raise GNS3ProviderError("GNS3 did not return a usable project identifier")
        return {
            key: value[key] for key in ("project_id", "name", "status", "scene_width", "scene_height")
            if key in value
        }

    def delete_lab(self, project_id: str) -> dict:
        project = self._segment(project_id, "project_id")
        self._request("DELETE", f"/v2/projects/{project}")
        return {"project_id": project_id, "deleted": True}

    def delete_node(self, project_id: str, node_id: str) -> dict:
        project = self._segment(project_id, "project_id")
        node = self._segment(node_id, "node_id")
        self._request("DELETE", f"/v2/projects/{project}/nodes/{node}")
        return {"project_id": project_id, "node_id": node_id, "deleted": True}

    def get_node_state(self, project_id: str, node_id: str) -> dict:
        project = self._segment(project_id, "project_id")
        node = self._segment(node_id, "node_id")
        value = self._request("GET", f"/v2/projects/{project}/nodes/{node}")
        if not isinstance(value, dict) or value.get("node_id") != node_id:
            raise GNS3ProviderError("GNS3 node-state response is invalid")
        allowed = (
            "node_id", "name", "node_type", "status", "template_id", "compute_id",
            "console_type", "console_host", "console", "x", "y", "ports",
        )
        result = {key: value[key] for key in allowed if key in value}
        ports = value.get("ports")
        if isinstance(ports, list):
            result["ports"] = [
                {
                    key: port[key]
                    for key in ("adapter_number", "port_number", "name", "short_name", "link_type")
                    if key in port
                }
                for port in ports if isinstance(port, dict)
            ]
        return result

    def delete_link(self, project_id: str, link_id: str) -> dict:
        project = self._segment(project_id, "project_id")
        link = self._segment(link_id, "link_id")
        self._request("DELETE", f"/v2/projects/{project}/links/{link}")
        return {"project_id": project_id, "link_id": link_id, "deleted": True}

    def get_interfaces(self, project_id: str, node_id: str) -> list[dict]:
        node = self.get_node_state(project_id, node_id)
        ports = node.get("ports")
        if not isinstance(ports, list):
            return []
        return [
            {
                "adapter_number": item.get("adapter_number"),
                "port_number": item.get("port_number"),
                "name": item.get("name"),
                "short_name": item.get("short_name"),
                "link_type": item.get("link_type"),
            }
            for item in ports if isinstance(item, dict)
        ]

    def get_observed_topology(self, project_id: str) -> dict:
        """Read actual nodes and links; this never creates or repairs provider resources."""
        return {
            "project_id": project_id,
            "nodes": self.list_nodes(project_id),
            "links": self.list_links(project_id),
        }

    def capture_support(self) -> dict:
        """Report adapter-level link-capture support, not per-link readiness."""
        return {
            "supported": True,
            "scope": "link",
            "start_path": "/v2/projects/{project_id}/links/{link_id}/start_capture",
            "stop_path": "/v2/projects/{project_id}/links/{link_id}/stop_capture",
            "readiness": "Controller, compute and link availability must be checked for each capture",
        }

