"""Project-scoped credential metadata backed by the host OS secret store.

Only opaque secret references are persisted in SQLite. Secret material is
resolved transiently and never returned in API records.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import secrets
from typing import Callable, Mapping


class CredentialVaultError(RuntimeError):
    """A credential operation failed without disclosing secret material."""


class CredentialVaultNotFound(CredentialVaultError):
    """The credential does not exist or is outside the requested scope."""


class CredentialVaultPolicyError(CredentialVaultError):
    """A credential lifecycle transition is not permitted."""


class CredentialVaultService:
    CREDENTIAL_TYPES = frozenset({"SSH_PASSWORD", "SSH_PRIVATE_KEY", "WIFI_PSK", "API_TOKEN"})

    def __init__(self, database, secret_store, *, secret_provider: str) -> None:
        self.database = database
        self.secret_store = secret_store
        self.secret_provider = str(secret_provider).strip().lower() or "os"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_actor(actor: object) -> str:
        value = str(actor or "").strip()
        if not value or len(value) > 128 or any(ord(char) < 33 for char in value):
            raise ValueError("actor must contain 1 to 128 non-control characters")
        return value

    @staticmethod
    def _safe_label(value: object) -> str:
        label = str(value or "").strip()
        if not label or len(label) > 120 or any(ord(char) < 32 for char in label):
            raise ValueError("credential label must contain 1 to 120 printable characters")
        return label

    @staticmethod
    def _safe_identifier(value: object, name: str) -> str:
        result = str(value or "").strip()
        if not result or len(result) > 128 or any(ord(char) < 33 for char in result):
            raise ValueError(f"{name} must contain 1 to 128 non-control characters")
        return result

    @staticmethod
    def _serialize(row) -> dict:
        return {
            "credential_id": row["credential_id"],
            "project_id": row["project_id"],
            "device_id": row["device_id"],
            "label": row["label"],
            "credential_type": row["credential_type"],
            "username": row["username"],
            "secret_provider": row["secret_provider"],
            "status": row["status"],
            "verification_status": row["verification_status"],
            "last_verified_at": row["last_verified_at"],
            "verification_summary": row["verification_summary"],
            "rotated_at": row["rotated_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "created_by": row["created_by"],
            "updated_by": row["updated_by"],
        }

    @staticmethod
    def _audit(connection, actor: str, action: str, credential_id: str, details: dict) -> None:
        connection.execute(
            """INSERT INTO audit_events(
                audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "AUD-" + secrets.token_hex(12), actor, action, "CREDENTIAL", credential_id,
                json.dumps(details, sort_keys=True, separators=(",", ":")),
                CredentialVaultService._now(),
            ),
        )

    def _get_raw(self, credential_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM managed_credentials WHERE credential_id=?",
                (credential_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get(self, credential_id: str) -> dict | None:
        row = self._get_raw(credential_id)
        return self._serialize(row) if row is not None else None

    def list(self, project_id: str, *, device_id: str | None = None) -> list[dict]:
        query = "SELECT * FROM managed_credentials WHERE project_id=?"
        parameters: list[object] = [project_id]
        if device_id:
            query += " AND device_id=?"
            parameters.append(device_id)
        query += " ORDER BY device_id COLLATE NOCASE,label COLLATE NOCASE,credential_id"
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._serialize(row) for row in rows]

    @staticmethod
    def _validate_secret(secret: object) -> str:
        if not isinstance(secret, str) or not secret or len(secret.encode("utf-8")) > 65536:
            raise ValueError("secret must be a non-empty UTF-8 value no larger than 64 KiB")
        if "\x00" in secret:
            raise ValueError("secret cannot contain a NUL character")
        return secret

    def create(
        self, *, project_id: str, device_id: str, label: str,
        credential_type: str, username: str | None, secret: str, actor: str,
    ) -> dict:
        project_id = self._safe_identifier(project_id, "project_id")
        device_id = self._safe_identifier(device_id, "device_id")
        label = self._safe_label(label)
        credential_type = str(credential_type or "").strip().upper()
        if credential_type not in self.CREDENTIAL_TYPES:
            raise ValueError("unsupported credential_type")
        username = str(username).strip() if username is not None else None
        if username is not None and (not username or len(username) > 128):
            raise ValueError("username must contain 1 to 128 characters when supplied")
        secret = self._validate_secret(secret)
        actor = self._safe_actor(actor)
        credential_id = secrets.token_hex(16)
        secret_reference = "netregress-cred-" + credential_id
        now = self._now()
        try:
            self.secret_store.set(secret_reference, secret)
        except Exception as exc:
            raise CredentialVaultError(
                "the configured operating-system secret store could not save this credential"
            ) from exc
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO managed_credentials(
                        credential_id,project_id,device_id,label,credential_type,username,
                        secret_provider,secret_reference,status,verification_status,
                        last_verified_at,verification_summary,rotated_at,created_at,
                        updated_at,created_by,updated_by
                    ) VALUES(?,?,?,?,?,?,?,?,'ACTIVE','NOT_VERIFIED',NULL,NULL,NULL,?,?,?,?)""",
                    (
                        credential_id, project_id, device_id, label, credential_type, username,
                        self.secret_provider, secret_reference, now, now, actor, actor,
                    ),
                )
                self._audit(
                    connection, actor, "CREDENTIAL_CREATED", credential_id,
                    {"project_id": project_id, "device_id": device_id, "credential_type": credential_type},
                )
        except Exception as exc:
            try:
                self.secret_store.delete(secret_reference)
            except Exception:
                pass
            if "UNIQUE constraint failed" in str(exc):
                raise CredentialVaultPolicyError(
                    "a credential with this label already exists for the selected device and Project"
                ) from exc
            if "FOREIGN KEY constraint failed" in str(exc):
                raise CredentialVaultNotFound("the selected Project no longer exists") from exc
            raise CredentialVaultError("credential metadata could not be committed") from exc
        result = self.get(credential_id)
        assert result is not None
        return result

    def rotate(
        self, credential_id: str, *, secret: str, actor: str, username: str | None = None
    ) -> dict:
        record = self._get_raw(credential_id)
        if record is None:
            raise CredentialVaultNotFound("credential not found")
        if record["status"] != "ACTIVE":
            raise CredentialVaultPolicyError("revoked credentials cannot be rotated")
        secret = self._validate_secret(secret)
        actor = self._safe_actor(actor)
        updated_username = record["username"] if username is None else str(username).strip()
        if updated_username is not None and (not updated_username or len(updated_username) > 128):
            raise ValueError("username must contain 1 to 128 characters when supplied")
        previous_secret = None
        try:
            previous_secret = self.secret_store.get(record["secret_reference"])
            if previous_secret is None:
                raise CredentialVaultError("the OS secret reference is unavailable")
            self.secret_store.set(record["secret_reference"], secret)
            now = self._now()
            with self.database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    """UPDATE managed_credentials
                       SET username=?,verification_status='NOT_VERIFIED',
                           last_verified_at=NULL,verification_summary=NULL,
                           rotated_at=?,updated_at=?,updated_by=?
                       WHERE credential_id=? AND status='ACTIVE'""",
                    (updated_username, now, now, actor, credential_id),
                )
                if cursor.rowcount != 1:
                    raise CredentialVaultPolicyError("credential is no longer active")
                self._audit(
                    connection, actor, "CREDENTIAL_ROTATED", credential_id,
                    {"project_id": record["project_id"], "device_id": record["device_id"]},
                )
        except Exception as exc:
            if previous_secret is not None:
                try:
                    self.secret_store.set(record["secret_reference"], previous_secret)
                except Exception as restore_error:
                    raise CredentialVaultError(
                        "credential metadata update failed and the prior secret could not be restored"
                    ) from restore_error
            if isinstance(exc, (CredentialVaultError, CredentialVaultPolicyError, ValueError)):
                raise
            raise CredentialVaultError("credential rotation failed") from exc
        result = self.get(credential_id)
        assert result is not None
        return result

    def revoke(self, credential_id: str, *, actor: str) -> dict:
        record = self._get_raw(credential_id)
        if record is None:
            raise CredentialVaultNotFound("credential not found")
        if record["status"] == "REVOKED":
            return {"credential": self._serialize(record), "secret_deleted": True}
        actor = self._safe_actor(actor)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE managed_credentials
                   SET status='REVOKED',verification_status='UNAVAILABLE',
                       verification_summary='Credential revoked',updated_at=?,updated_by=?
                   WHERE credential_id=? AND status='ACTIVE'""",
                (now, actor, credential_id),
            )
            if cursor.rowcount != 1:
                raise CredentialVaultPolicyError("credential is no longer active")
            self._audit(
                connection, actor, "CREDENTIAL_REVOKED", credential_id,
                {"project_id": record["project_id"], "device_id": record["device_id"]},
            )
        secret_deleted = False
        try:
            secret_deleted = bool(self.secret_store.delete(record["secret_reference"]))
        except Exception:
            secret_deleted = False
        return {"credential": self.get(credential_id), "secret_deleted": secret_deleted}

    def verify(
        self, credential_id: str, *, actor: str,
        verifier: Callable[[Mapping[str, object], str], tuple[str, str]],
    ) -> dict:
        record = self._get_raw(credential_id)
        if record is None:
            raise CredentialVaultNotFound("credential not found")
        if record["status"] != "ACTIVE":
            raise CredentialVaultPolicyError("revoked credentials cannot be verified")
        actor = self._safe_actor(actor)
        status = "UNAVAILABLE"
        summary = "The secret provider did not return a credential."
        try:
            secret = self.secret_store.get(record["secret_reference"])
            if secret:
                result_status, result_summary = verifier(record, secret)
                status = str(result_status).upper()
                if status not in {"VERIFIED", "FAILED", "UNAVAILABLE"}:
                    raise ValueError("verifier returned an invalid status")
                summary = str(result_summary)[:240]
        except Exception as exc:
            status = "UNAVAILABLE"
            summary = "Credential verification could not run (" + type(exc).__name__ + ")."
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE managed_credentials
                   SET verification_status=?,last_verified_at=?,verification_summary=?,
                       updated_at=?,updated_by=?
                   WHERE credential_id=? AND status='ACTIVE'""",
                (status, now, summary, now, actor, credential_id),
            )
            if cursor.rowcount != 1:
                raise CredentialVaultPolicyError("credential was revoked during verification")
            self._audit(
                connection, actor, "CREDENTIAL_VERIFICATION_RECORDED", credential_id,
                {"verification_status": status, "project_id": record["project_id"]},
            )
        return self.get(credential_id) or {}
