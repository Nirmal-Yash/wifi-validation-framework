"""Vault-scoped provider adapter construction and connection lifecycle."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class ProviderSessionError(RuntimeError):
    """A provider session could not be established or closed safely."""


class ProviderSessionService:
    """The single credential-to-adapter boundary shared by provider consumers."""

    def __init__(self, credential_vault, provider_registry):
        if not callable(getattr(credential_vault, "use_secret", None)):
            raise TypeError("credential_vault must expose use_secret")
        if not callable(getattr(provider_registry, "create", None)):
            raise TypeError("provider_registry must expose create")
        self.credential_vault = credential_vault
        self.provider_registry = provider_registry

    def with_provider(self, binding: Mapping[str, Any], actor: str, callback: Callable[[Any], Any]):
        if not isinstance(binding, Mapping):
            raise ProviderSessionError("provider binding must be a mapping")
        if not callable(callback):
            raise TypeError("provider callback must be callable")
        required = ("endpoint_url", "project_id", "controller_device_id", "credential_id")
        missing = [key for key in required if not isinstance(binding.get(key), str) or not binding[key]]
        if missing:
            raise ProviderSessionError("provider binding is missing required session fields")

        provider_id = str(binding.get("provider_id") or "gns3")

        def invoke(record: Mapping[str, object], secret: str):
            username = str(record.get("username") or "")
            adapter = self.provider_registry.create(provider_id, binding["endpoint_url"], username, secret)
            primary_error = None
            try:
                adapter.connect()
                return callback(adapter)
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                # GNS3 currently uses short-lived per-request HTTP sessions; this
                # logical disconnect also gives future adapters one cleanup seam.
                try:
                    adapter.disconnect()
                except Exception as exc:
                    if primary_error is None:
                        raise ProviderSessionError("provider session cleanup failed") from exc

        return self.credential_vault.use_secret(
            binding["credential_id"],
            project_id=binding["project_id"],
            device_id=binding["controller_device_id"],
            credential_type="API_TOKEN",
            actor=actor,
            consumer=invoke,
        )
