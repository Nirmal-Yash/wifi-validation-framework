from __future__ import annotations

from scripts.seed_demo_showcase import RunnerAPIError, RunnerClient, validate_loopback_api_base


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
