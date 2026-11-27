from __future__ import annotations

from scripts.seed_demo_showcase import RunnerAPIError, RunnerClient, topology_profile_counts, validate_loopback_api_base


class FakeHeaderCollection:
    def getlist(self, name):
        if name == "Set-Cookie":
            return ["session=opaque-session-value; HttpOnly; Path=/; Secure; SameSite=None"]
        return []


class FakeResponse:
    status_code = 200
    ok = True
    headers = {"Set-Cookie": "session=opaque-session-value; HttpOnly; Path=/; Secure; SameSite=None"}
    raw = type("Raw", (), {"headers": FakeHeaderCollection()})()

    def json(self):
        return {"data": {"csrf_token": "csrf-demo-token"}}


class FakeSession:
    def __init__(self):
        self.trust_env = True
        self.login = None
        self.request_call = None

    def post(self, url, *, json, timeout):
        self.login = {"url": url, "json": json, "timeout": timeout}
        return FakeResponse()

    def request(self, method, url, **kwargs):
        self.request_call = {"method": method, "url": url, **kwargs}
        return FakeResponse()


def test_demo_api_base_must_be_loopback_and_include_api_prefix():
    assert validate_loopback_api_base("http://127.0.0.1:5050/api/v1") == "http://127.0.0.1:5050/api/v1/"
    assert validate_loopback_api_base("http://[::1]:5050/api/v1") == "http://[::1]:5050/api/v1/"
    try:
        validate_loopback_api_base("https://example.com/api/v1")
    except RunnerAPIError as exc:
        assert "loopback" in str(exc).lower()
    else:
        raise AssertionError("remote API endpoint was accepted")


def test_runner_client_forwards_secure_cookie_only_to_loopback(monkeypatch):
    fake = FakeSession()
    monkeypatch.setattr("scripts.seed_demo_showcase.requests.Session", lambda: fake)

    client = RunnerClient("http://127.0.0.1:5050/api/v1", "demo-owner", "not-persisted")
    client.request("POST", "workspace/projects", json_body={"name": "Demo"})

    assert fake.trust_env is False
    assert fake.login["json"] == {"username": "demo-owner", "password": "not-persisted"}
    assert fake.request_call["headers"]["Cookie"] == "session=opaque-session-value"
    assert fake.request_call["headers"]["X-CSRF-Token"] == "csrf-demo-token"
    assert fake.request_call["headers"]["Idempotency-Key"]
    assert "Secure" not in fake.request_call["headers"]["Cookie"]
    assert "SameSite" not in fake.request_call["headers"]["Cookie"]


class FakeTopologyRevisionClient:
    def __init__(self, revisions):
        self.revisions = revisions

    def get_items(self, path):
        assert path == "topologies/profile-1/revisions"
        return self.revisions


def test_demo_seeder_verifies_existing_profile_has_real_nodes_and_links():
    client = FakeTopologyRevisionClient([{
        "revision_number": 2,
        "definition": {"nodes": [{"id": "r1"}, {"id": "sw1"}], "links": [{"id": "uplink"}]},
    }])
    counts = topology_profile_counts(client, {"profile_id": "profile-1", "name": "Branch demo"})
    assert counts == {"nodes": 2, "links": 1, "revision_number": 2}


def test_demo_seeder_refuses_to_reuse_an_empty_topology_profile():
    client = FakeTopologyRevisionClient([{
        "revision_number": 1,
        "definition": {"nodes": [], "links": []},
    }])
    try:
        topology_profile_counts(client, {"profile_id": "profile-1", "name": "Empty demo"})
    except RunnerAPIError as exc:
        assert "empty latest revision" in str(exc)
    else:
        raise AssertionError("empty topology profile was reported as a successful demo import")


def test_demo_seeder_refuses_a_profile_without_any_revision():
    client = FakeTopologyRevisionClient([])
    try:
        topology_profile_counts(client, {"profile_id": "profile-1", "name": "Missing revision"})
    except RunnerAPIError as exc:
        assert "without a revision" in str(exc)
    else:
        raise AssertionError("topology profile without a revision was reused")
