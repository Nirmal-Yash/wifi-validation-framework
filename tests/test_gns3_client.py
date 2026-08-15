from types import SimpleNamespace

import pytest

from gns3fy import Gns3Connector, GNS3AuthenticationError, GNS3HTTPError, Project


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b"{}", headers=None, text=""):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = text
        self.ok = 200 <= status < 400

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.auth = None
        self.headers = {}

    def request(self, method, url, timeout=None, **kwargs):
        return self.responses.pop(0)


def test_connector_uses_basic_auth(monkeypatch):
    connector = Gns3Connector("http://localhost:3080", "admin", "secret")
    assert connector.session.auth == ("admin", "secret")


def test_401_is_reported_as_authentication_error():
    connector = Gns3Connector("http://localhost:3080", "admin", "wrong")
    connector.session = FakeSession([FakeResponse(status=401, content=b"")])
    with pytest.raises(GNS3AuthenticationError):
        connector.request("GET", "/v2/version")


def test_empty_response_is_not_parsed_as_json():
    connector = Gns3Connector("http://localhost:3080", "admin", "secret")
    connector.session = FakeSession([FakeResponse(status=200, content=b"")])
    with pytest.raises(GNS3HTTPError, match="empty response"):
        connector.request("GET", "/v2/version")


def test_project_loads_nodes_and_links():
    connector = Gns3Connector("http://localhost:3080", "admin", "secret")
    connector.session = FakeSession([
        FakeResponse(payload={"project_id": "p1", "name": "Lab"}),
        FakeResponse(payload=[{"node_id": "r1", "name": "R1", "node_type": "router", "x": 1, "y": 2}]),
        FakeResponse(payload=[{"link_id": "l1", "nodes": [{"node_id": "r1"}, {"node_id": "r2"}]}]),
    ])
    project = Project("p1", connector=connector).get()
    assert project.name == "Lab"
    assert project.nodes[0].node_id == "r1"
    assert project.links[0].link_id == "l1"
