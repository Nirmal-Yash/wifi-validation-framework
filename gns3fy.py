"""Authenticated GNS3 API compatibility layer used by NetForge."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin

import requests


class GNS3Error(RuntimeError):
    pass


class GNS3AuthenticationError(GNS3Error):
    pass


class GNS3HTTPError(GNS3Error):
    pass


def _load_project_env():
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


_load_project_env()


class Gns3Connector:
    def __init__(self, url="http://localhost:3080", username=None, password=None, timeout=None):
        self.url = str(url).rstrip("/")
        self.username = username if username is not None else os.getenv("GNS3_USERNAME", "")
        self.password = password if password is not None else os.getenv("GNS3_PASSWORD", "")
        self.timeout = float(timeout or os.getenv("GNS3_TIMEOUT", "10"))
        self.session = requests.Session()
        if self.username or self.password:
            self.session.auth = (self.username, self.password)
        self.session.headers.update({"Accept": "application/json"})

    def request(self, method, path, **kwargs):
        url = urljoin(self.url + "/", path.lstrip("/"))
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise GNS3Error(f"Unable to reach GNS3 at {self.url}: {exc}") from exc
        if response.status_code == 401:
            raise GNS3AuthenticationError(f"GNS3 authentication failed for {self.url}.")
        if response.status_code == 403:
            raise GNS3AuthenticationError(f"GNS3 denied access to {path} (HTTP 403).")
        if not response.ok:
            body = response.text.strip()
            detail = body[:300] if body else "empty response"
            raise GNS3HTTPError(f"GNS3 returned HTTP {response.status_code} for {path}: {detail}")
        if not response.content:
            raise GNS3HTTPError(f"GNS3 returned an empty response for {path}.")
        try:
            return response.json()
        except ValueError as exc:
            content_type = response.headers.get("Content-Type", "unknown")
            raise GNS3HTTPError(f"GNS3 returned invalid JSON for {path} (Content-Type: {content_type}).") from exc


class Project:
    def __init__(self, project_id, connector=None, **kwargs):
        self.project_id = str(project_id)
        self.connector = connector or Gns3Connector(**kwargs)
        self.nodes = []
        self.links = []
        self.name = None
        self.status = None

    def get(self):
        data = self.connector.request("GET", f"/v2/projects/{self.project_id}")
        self.name = data.get("name")
        self.status = data.get("status")
        self.nodes = [self._node(n) for n in self.connector.request("GET", f"/v2/projects/{self.project_id}/nodes")]
        self.links = [self._link(l) for l in self.connector.request("GET", f"/v2/projects/{self.project_id}/links")]
        return self

    @staticmethod
    def _node(data):
        return SimpleNamespace(node_id=data.get("node_id"), name=data.get("name") or data.get("node_id"), x=data.get("x", 0), y=data.get("y", 0), node_type=data.get("node_type") or data.get("type", "generic"))

    @staticmethod
    def _link(data):
        nodes = data.get("nodes") or []
        return SimpleNamespace(link_id=data.get("link_id"), nodes=nodes, suspend=bool(data.get("suspend", False)))
