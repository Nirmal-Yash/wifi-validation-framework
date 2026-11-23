"""Shared hardened HTTP primitives for REST-backed topology providers."""
from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit

import requests

from lib.services.gns3_provider import GNS3Provider, GNS3ProviderError


class ProviderHTTPError(RuntimeError):
    """Sanitized provider HTTP, authentication or response-contract failure."""


def validate_provider_endpoint(value: object, *, expected_host: str | None = None) -> str:
    try:
        return GNS3Provider.validate_endpoint(value, expected_host=expected_host)
    except GNS3ProviderError as exc:
        raise ProviderHTTPError(str(exc)) from exc


class ProviderHTTPSession:
    """A short-lived, environment-independent, bounded and TLS-verified HTTP session."""

    MAX_RESPONSE_BYTES = 4 * 1024 * 1024
    TIMEOUT = (3.05, 25.0)

    def __init__(self, endpoint_url: str, *, session_factory=None):
        self.endpoint_url = validate_provider_endpoint(endpoint_url)
        self.session_factory = session_factory or requests.Session
        self.session = self.session_factory()
        self.session.trust_env = False
        self.closed = False

    def request(self, method: str, path: str, *, payload=None, headers=None, params=None):
        if self.closed:
            raise ProviderHTTPError("provider HTTP session is closed")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ProviderHTTPError("provider API path is invalid")
        try:
            response = self.session.request(
                method.upper(), self.endpoint_url + path, json=payload, params=params,
                headers={"Accept": "application/json", **(headers or {})},
                timeout=self.TIMEOUT, verify=True, allow_redirects=False, stream=True,
            )
            try:
                status = int(response.status_code)
                if status < 200 or status >= 300:
                    raise ProviderHTTPError(
                        f"provider returned HTTP {status} for {method.upper()} {path.split('?')[0]}"
                    )
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.MAX_RESPONSE_BYTES:
                        raise ProviderHTTPError("provider response exceeded the 4 MiB safety limit")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                if not raw:
                    return None
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProviderHTTPError("provider returned an invalid JSON response") from exc
            finally:
                response.close()
        except ProviderHTTPError:
            raise
        except requests.RequestException as exc:
            raise ProviderHTTPError("provider request failed (" + type(exc).__name__ + ")") from exc

    def close(self):
        if not self.closed:
            self.closed = True
            self.session.close()
