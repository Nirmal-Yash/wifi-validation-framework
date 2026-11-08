from __future__ import annotations

import socket

import pytest

from lib.services.api_security import RequestSecurityError, validate_https_endpoint


def _answer(address: str):
    return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443, 0, 0) if ":" in address else (address, 443))]


@pytest.mark.parametrize("url", [
    "http://example.com",
    "https://user:pass@example.com",
    "https://example.com:99999",
    "https://example.com/#fragment",
])
def test_https_endpoint_rejects_invalid_url_forms(url):
    with pytest.raises(RequestSecurityError):
        validate_https_endpoint(url)


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.1", "169.254.1.1", "192.0.2.10",
    "100.64.0.1", "240.0.0.1", "::1", "fc00::1", "fe80::1", "2001:db8::1",
])
def test_https_endpoint_rejects_every_non_global_dns_answer(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _answer(address))
    with pytest.raises(RequestSecurityError, match="non-public"):
        validate_https_endpoint("https://example.test")


def test_https_endpoint_rejects_mixed_public_and_private_dns_answers(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _answer("8.8.8.8") + _answer("10.0.0.2"))
    with pytest.raises(RequestSecurityError, match="non-public"):
        validate_https_endpoint("https://example.test")


def test_https_endpoint_rejects_empty_dns_answer(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(RequestSecurityError, match="no usable address"):
        validate_https_endpoint("https://example.test")


def test_https_endpoint_accepts_global_ipv4_and_ipv6(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _answer("8.8.8.8") + _answer("2606:4700:4700::1111"))
    assert validate_https_endpoint("https://example.test") == "https://example.test"
