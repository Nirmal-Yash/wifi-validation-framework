from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")

class RequestSecurityError(ValueError):
    pass

@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    scope: str
    key: str
    request_sha256: str
    response: dict[str, Any]
    status_code: int
    expires_at: datetime

class IdempotencyStore:
    """Durable replay/idempotency cache for state-changing requests."""
    def __init__(self, database: Any, *, ttl_seconds: int = 3600):
        self.database = database
        self.ttl_seconds = max(60, ttl_seconds)
        self._ensure_table()

    def _ensure_table(self) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS api_idempotency (
                    scope TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL DEFAULT '',
                    response_json TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY(scope, idempotency_key)
                )"""
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(api_idempotency)").fetchall()}
            if "request_sha256" not in columns:
                connection.execute("ALTER TABLE api_idempotency ADD COLUMN request_sha256 TEXT NOT NULL DEFAULT ''")
            connection.commit()

    @staticmethod
    def validate_key(value: str) -> str:
        key = str(value or "").strip()
        if not _IDEMPOTENCY_RE.fullmatch(key):
            raise RequestSecurityError(
                "Idempotency-Key must be 8-128 characters and use only A-Z, a-z, 0-9, '.', '_' , ':' or '-'."
            )
        return key

    def get(self, scope: str, key: str, request_sha256: str | None = None) -> IdempotencyRecord | None:
        now = datetime.now(timezone.utc)
        with self.database.connection() as connection:
            connection.execute("DELETE FROM api_idempotency WHERE expires_at <= ?", (now.isoformat(),))
            row = connection.execute(
                "SELECT * FROM api_idempotency WHERE scope = ? AND idempotency_key = ?",
                (scope, key),
            ).fetchone()
        if not row:
            return None
        stored_hash = row["request_sha256"] or ""
        if request_sha256 is not None and stored_hash and not hmac.compare_digest(stored_hash, request_sha256):
            raise RequestSecurityError("Idempotency-Key was already used for a different request")
        return IdempotencyRecord(
            scope, key, stored_hash, json.loads(row["response_json"]),
            int(row["status_code"]), datetime.fromisoformat(row["expires_at"])
        )

    def put(self, scope: str, key: str, request_sha256: str, response: dict[str, Any], status_code: int) -> IdempotencyRecord:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self.ttl_seconds)
        with self.database.connection() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO api_idempotency(
                    scope,idempotency_key,request_sha256,response_json,status_code,created_at,expires_at
                ) VALUES (?,?,?,?,?,?,?)""",
                (
                    scope, key, request_sha256,
                    json.dumps(response, sort_keys=True, separators=(",", ":")),
                    status_code, now.isoformat(), expires.isoformat(),
                ),
            )
            connection.commit()
        stored = self.get(scope, key, request_sha256)
        assert stored is not None
        return stored

class CsrfService:
    @staticmethod
    def token(session: Any) -> str:
        current = session.get("netregress_csrf")
        if not current:
            current = secrets.token_urlsafe(32)
            session["netregress_csrf"] = current
        return current

    @staticmethod
    def validate(session: Any, supplied: str | None) -> bool:
        expected = session.get("netregress_csrf")
        return bool(expected and supplied and hmac.compare_digest(expected, supplied))

def apply_security_headers(response: Any, *, no_store: bool = False, hsts: bool = False) -> Any:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if no_store:
        response.headers.setdefault("Cache-Control", "no-store")
    if hsts:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

class LoginRateLimiter:
    def __init__(self, *, window_seconds: int = 60, max_attempts: int = 8):
        self.window_seconds = window_seconds
        self.max_attempts = max_attempts
        self._attempts: dict[str, list[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        import time
        current = now if now is not None else time.monotonic()
        recent = [item for item in self._attempts.get(key, []) if current - item < self.window_seconds]
        if len(recent) >= self.max_attempts:
            self._attempts[key] = recent
            return False
        recent.append(current)
        self._attempts[key] = recent
        if len(self._attempts) > 2048:
            self._attempts = {
                k: v for k, v in self._attempts.items()
                if v and current - v[-1] < self.window_seconds
            }
        return True

def validate_https_endpoint(url: str) -> str:
    parsed = urlparse(str(url))
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RequestSecurityError("outbound endpoint must be an HTTPS URL without embedded credentials")
    host = parsed.hostname
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise RequestSecurityError("outbound endpoint hostname cannot be resolved") from exc
    blocked = []
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            blocked.append(address)
    if blocked:
        raise RequestSecurityError("outbound endpoint resolves to a non-public IP address")
    return parsed.geturl()

def resolve_confined_path(path: str | Path, root: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    base = Path(root).expanduser().resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise RequestSecurityError("path is outside the configured security boundary") from exc
    return candidate
