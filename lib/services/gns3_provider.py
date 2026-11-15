"""Bounded, credential-injected client for the local GNS3 Controller API."""
from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import quote, urlsplit

import requests


class GNS3ProviderError(RuntimeError):
    """A sanitized GNS3 transport or contract failure."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class GNS3Provider:
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
        return [
            {key: item[key] for key in ("template_id", "name", "category", "builtin") if key in item}
            for item in value if isinstance(item, dict)
        ]

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
