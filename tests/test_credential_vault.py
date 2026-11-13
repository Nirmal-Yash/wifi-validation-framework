from __future__ import annotations

import pytest

from lib.repositories import SQLiteDatabase
from lib.services.credential_vault import (
    CredentialVaultError, CredentialVaultPolicyError, CredentialVaultService,
)


class MemorySecretStore:
    def __init__(self):
        self.values = {}
    def set(self, name, secret):
        self.values[name] = secret
    def get(self, name):
        return self.values.get(name)
    def delete(self, name):
        return self.values.pop(name, None) is not None


@pytest.fixture
def vault(tmp_path):
    database = SQLiteDatabase(tmp_path / "credentials.sqlite")
    database.initialize()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at)
               VALUES('org-1','org','Organization','ACTIVE','2026-11-13T00:00:00+00:00','2026-11-13T00:00:00+00:00')"""
        )
        connection.execute(
            """INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at)
               VALUES('project-1','org-1','project','Project','ACTIVE','2026-11-13T00:00:00+00:00','2026-11-13T00:00:00+00:00')"""
        )
    store = MemorySecretStore()
    service = CredentialVaultService(database, store, secret_provider="test-os-vault")
    return database, store, service


def create_sample(service, label="Primary SSH", secret="do-not-persist-this"):
    return service.create(
        project_id="project-1", device_id="ap-1", label=label,
        credential_type="SSH_PASSWORD", username="root", secret=secret, actor="owner",
    )


def test_credential_create_keeps_secret_outside_sqlite_and_serialization(vault):
    database, store, service = vault
    item = create_sample(service)
    assert item["status"] == "ACTIVE"
    assert item["verification_status"] == "NOT_VERIFIED"
    assert "do-not-persist-this" not in repr(item)
    assert len(store.values) == 1
    with database.connection() as connection:
        row = connection.execute(
            "SELECT * FROM managed_credentials WHERE credential_id=?",
            (item["credential_id"],),
        ).fetchone()
        assert "do-not-persist-this" not in repr(dict(row))
        assert row["secret_reference"] in store.values
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1


def test_credential_list_is_project_and_device_scoped(vault):
    _database, _store, service = vault
    first = create_sample(service)
    service.create(
        project_id="project-1", device_id="router-1", label="Primary SSH",
        credential_type="SSH_PASSWORD", username="root", secret="secret-b", actor="owner",
    )
    assert [item["credential_id"] for item in service.list("project-1", device_id="ap-1")] == [first["credential_id"]]
    assert service.list("another-project") == []


def test_credential_rotation_resets_verification_and_preserves_metadata(vault):
    _database, store, service = vault
    item = create_sample(service, secret="old-secret")
    verified = service.verify(
        item["credential_id"], actor="operator",
        verifier=lambda record, secret: ("VERIFIED", "SSH probe passed"),
    )
    assert verified["verification_status"] == "VERIFIED"
    rotated = service.rotate(item["credential_id"], secret="new-secret", actor="owner")
    assert rotated["username"] == "root"
    assert rotated["verification_status"] == "NOT_VERIFIED"
    assert store.values["netregress-cred-" + rotated["credential_id"]] == "new-secret"
    assert rotated["rotated_at"] is not None


def test_credential_verification_never_echoes_provider_errors_or_secret_values(vault):
    _database, _store, service = vault
    item = create_sample(service, secret="private-secret")
    result = service.verify(
        item["credential_id"], actor="operator",
        verifier=lambda record, secret: (_ for _ in ()).throw(RuntimeError("private-secret")),
    )
    assert result["verification_status"] == "UNAVAILABLE"
    assert "private-secret" not in result["verification_summary"]


def test_credential_revoke_deletes_os_secret_and_is_soft_idempotent(vault):
    database, store, service = vault
    item = create_sample(service, secret="private-secret")
    revoked = service.revoke(item["credential_id"], actor="owner")
    assert revoked["credential"]["status"] == "REVOKED"
    assert revoked["secret_deleted"] is True
    assert store.values == {}
    assert service.revoke(item["credential_id"], actor="owner")["secret_deleted"] is True
    with database.connection() as connection:
        with pytest.raises(Exception, match="managed credentials must be revoked"):
            connection.execute("DELETE FROM managed_credentials WHERE credential_id=?", (item["credential_id"],))


def test_credential_create_compensates_os_secret_when_metadata_conflicts(vault):
    _database, store, service = vault
    create_sample(service, label="same", secret="secret-a")
    with pytest.raises(CredentialVaultPolicyError):
        create_sample(service, label="same", secret="secret-b")
    assert len(store.values) == 1


def test_credential_provider_failure_is_sanitized(vault):
    database, _store, _service = vault
    class BrokenStore:
        def set(self, name, secret):
            raise RuntimeError("private-secret failed")
        def get(self, name):
            raise RuntimeError("private-secret failed")
        def delete(self, name):
            raise RuntimeError("private-secret failed")
    broken = CredentialVaultService(database, BrokenStore(), secret_provider="broken")
    with pytest.raises(CredentialVaultError) as error:
        broken.create(
            project_id="project-1", device_id="router-1", label="bad",
            credential_type="SSH_PASSWORD", username="root", secret="private-secret", actor="owner",
        )
    assert "private-secret" not in str(error.value)
