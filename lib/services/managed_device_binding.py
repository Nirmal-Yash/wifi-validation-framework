"""Bind an inventory Device to its registered Runner adapter and vault credential."""
from __future__ import annotations

from typing import Any, Mapping

from lib.adapters.device import DeviceProfile
from lib.connector import load_devices
from lib.services.device_inventory import DeviceInventoryService


class ManagedDeviceBindingError(ValueError):
    """A managed Device cannot be safely bound to a Runner adapter."""


def build_managed_device_profile(
    database,
    credential_vault,
    *,
    managed_device_id: str,
    project_id: str,
    lab_id: str,
    actor: str,
    ssh_credential_id: str | None = None,
    device_profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[DeviceProfile, dict[str, str | int]]:
    """Resolve a same-Project/Lab Device without exposing its secret to the caller.

    Only a registered device_key can select a Runner adapter. The SSH password
    is obtained inside CredentialVaultService.use_secret and copied directly
    into the in-memory DeviceProfile; it is never put in argv, an environment
    variable, Run metadata, or the pipeline definition.
    """
    actor = str(actor or "").strip()
    if not actor or len(actor) > 128:
        raise ManagedDeviceBindingError("a valid Run actor is required for managed Device binding")

    device = DeviceInventoryService(database).get(str(managed_device_id or "").strip())
    if (
        device is None or device.get("status") != "ACTIVE"
        or device.get("project_id") != project_id
        or device.get("lab_id") != lab_id
    ):
        raise ManagedDeviceBindingError("managed Device must be active in the same Project/Lab as the Run")

    profiles = device_profiles if device_profiles is not None else load_devices()
    device_key = device.get("device_key")
    base_profile = profiles.get(device_key) if isinstance(profiles, Mapping) else None
    if not isinstance(base_profile, Mapping):
        raise ManagedDeviceBindingError(
            "managed Device key has no compatible Runner adapter profile in configs/devices.yaml"
        )

    credential_id = str(ssh_credential_id or device.get("credential_id") or "").strip()
    if not credential_id:
        raise ManagedDeviceBindingError("managed Device requires an SSH_PASSWORD Credential Vault reference")
    credential = credential_vault.get(credential_id)
    if (
        credential is None or credential.get("project_id") != project_id
        or credential.get("device_id") != device["device_id"]
        or credential.get("credential_type") != "SSH_PASSWORD"
        or credential.get("status") != "ACTIVE"
    ):
        raise ManagedDeviceBindingError(
            "managed Device requires an active same-device SSH_PASSWORD Credential Vault reference"
        )

    username = credential.get("username") or device.get("username")
    if not isinstance(username, str) or not username.strip():
        raise ManagedDeviceBindingError("managed Device SSH credential must include a username")

    secret_holder: dict[str, str] = {}

    def capture_secret(_record: Mapping[str, object], secret: str):
        if not isinstance(secret, str) or not secret:
            raise ManagedDeviceBindingError("managed Device SSH password is unavailable")
        secret_holder["password"] = secret
        return {"status": "resolved"}

    try:
        credential_vault.use_secret(
            credential_id,
            project_id=project_id,
            device_id=device["device_id"],
            credential_type="SSH_PASSWORD",
            actor=actor,
            consumer=capture_secret,
        )
        password = secret_holder.pop("password", None)
        if not password:
            raise ManagedDeviceBindingError("managed Device SSH password could not be resolved")
        values = dict(base_profile)
        values.update({
            "host": device["host"],
            "port": int(device["port"]),
            "username": username.strip(),
            "password": password,
            "key_filename": None,
            "device_type": str(base_profile.get("device_type", "linux")),
            "model": device.get("model") or base_profile.get("model", "unknown"),
        })
        profile = DeviceProfile.from_mapping(device_key, values)
    except ManagedDeviceBindingError:
        raise
    except Exception as exc:
        raise ManagedDeviceBindingError(
            "managed Device SSH credential could not be bound to its Runner adapter"
        ) from exc
    finally:
        secret_holder.clear()

    identity: dict[str, str | int] = {
        "device_id": device["device_id"],
        "device_key": device_key,
        "host": device["host"],
        "port": int(device["port"]),
        "username": username.strip(),
        "ssh_credential_id": credential_id,
    }
    return profile, identity
