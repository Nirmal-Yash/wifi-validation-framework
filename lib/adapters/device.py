from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
from typing import Any, Mapping, Protocol

import paramiko

from lib.services.command_runner import CommandResult, CommandRunner


_ENV_CREDENTIAL_RE = re.compile(r"^__ENV__:([A-Z0-9_]+)$")
_REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9_./-]+$")


def _coerce_bool(value: Any, *, name: str) -> bool:
    """Parse configuration booleans without Python's truthiness trap for strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    raise ValueError(f"{name} must be a boolean value")


def _resolve_credential(value: Any, *, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")
    if not value.startswith("__ENV__:"):
        return value
    match = _ENV_CREDENTIAL_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"{name} has an invalid environment-secret marker")
    secret = os.environ.get(match.group(1))
    if not secret:
        raise ValueError(f"required device credential environment variable is unset: {match.group(1)}")
    return secret


class DeviceAdapterError(RuntimeError): pass
class DeviceUnavailableError(DeviceAdapterError): pass
class DeviceCapabilityError(DeviceAdapterError): pass

@dataclass(frozen=True, slots=True)
class DeviceCapabilities:
    supports_wpa2: bool = True
    supports_wpa3: bool = False
    supports_2ghz: bool = True
    supports_5ghz: bool = True
    supports_6ghz: bool = False
    supports_reboot: bool = True
    supports_firmware_flash: bool = False
    supports_rollback: bool = False
    supports_rssi: bool = True
    supports_packet_capture: bool = True
    supports_ssh: bool = True
    supports_tftp: bool = False

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")

    def as_dict(self) -> dict[str, bool]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

@dataclass(frozen=True, slots=True)
class DeviceProfile:
    device_id: str
    host: str
    username: str
    port: int = 22
    password: str | None = field(default=None, repr=False)
    key_filename: str | None = field(default=None, repr=False)
    device_type: str = 'linux'
    model: str = 'unknown'
    capabilities: DeviceCapabilities = field(default_factory=DeviceCapabilities)
    health_command: str = 'true'
    version_command: str = 'uname -r'
    wifi_state_command: str = 'iw dev wlan0 link'
    network_state_command: str = 'ip -brief addr'
    reboot_command: str = 'reboot'
    firmware_flash_command: str = 'sysupgrade -n {remote_path}'
    firmware_rollback_command: str | None = None
    version_parser: str = 'first-line'
    remote_firmware_directory: str = '/tmp/netregress'

    def __post_init__(self) -> None:
        for name, value in (("device_id", self.device_id), ("host", self.host), ("username", self.username)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("device port must be an integer between 1 and 65535")
        directory = posixpath.normpath(self.remote_firmware_directory)
        if (
            not isinstance(self.remote_firmware_directory, str)
            or not directory.startswith("/")
            or directory == "/"
            or ".." in self.remote_firmware_directory.split("/")
            or not _REMOTE_PATH_RE.fullmatch(directory)
        ):
            raise ValueError("remote firmware directory must be a safe absolute path")
        object.__setattr__(self, "remote_firmware_directory", directory)

    @classmethod
    def from_mapping(cls, device_id: str, values: Mapping[str, Any]) -> 'DeviceProfile':
        if not isinstance(values, Mapping):
            raise ValueError("device profile must be a mapping")
        device_type = str(values.get('device_type', 'linux')).strip().lower()
        raw_caps = values.get('capabilities') or {}
        if not isinstance(raw_caps, Mapping):
            raise ValueError("device capabilities must be a mapping")
        defaults = (
            DeviceCapabilities(supports_wpa3=True, supports_firmware_flash=True)
            if device_type == "openwrt"
            else DeviceCapabilities()
        )
        unknown = set(raw_caps) - set(defaults.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown device capabilities: {', '.join(sorted(map(str, unknown)))}")
        caps = DeviceCapabilities(**{
            name: _coerce_bool(raw_caps.get(name, getattr(defaults, name)), name=name)
            for name in defaults.__dataclass_fields__
        })
        return cls(
            device_id=device_id, host=str(values['host']), username=str(values['username']),
            port=int(values.get('port', 22)),
            password=_resolve_credential(values.get('password'), name="password"),
            key_filename=_resolve_credential(values.get('key_filename'), name="key_filename"),
            device_type=device_type, model=str(values.get('model', 'unknown')), capabilities=caps,
            health_command=str(values.get('health_command', 'true')),
            version_command=str(values.get('version_command', 'ubus call system board' if device_type == 'openwrt' else 'uname -r')),
            wifi_state_command=str(values.get('wifi_state_command', 'iw dev wlan0 link')),
            network_state_command=str(values.get('network_state_command', 'ip -brief addr')),
            reboot_command=str(values.get('reboot_command', 'reboot')),
            firmware_flash_command=str(values.get('firmware_flash_command', 'sysupgrade -n {remote_path}')),
            firmware_rollback_command=values.get('firmware_rollback_command'),
            version_parser=str(values.get('version_parser', 'openwrt-ubus' if device_type == 'openwrt' else 'first-line')),
            remote_firmware_directory=str(values.get('remote_firmware_directory', '/tmp/netregress')),
        )

    @classmethod
    def openwrt_defaults(cls, *, device_id: str, host: str, username: str, port: int = 22,
                         password: str | None = None, key_filename: str | None = None,
                         model: str = 'openwrt', supports_rollback: bool = False,
                         firmware_rollback_command: str | None = None) -> 'DeviceProfile':
        return cls(
            device_id=device_id, host=host, username=username, port=port, password=password,
            key_filename=key_filename, device_type='openwrt', model=model,
            capabilities=DeviceCapabilities(supports_wpa3=True, supports_reboot=True,
                supports_firmware_flash=True, supports_rollback=supports_rollback),
            health_command='ubus call system board', version_command='ubus call system board',
            wifi_state_command='iw dev wlan0 link', network_state_command='ip -brief addr',
            reboot_command='reboot', firmware_flash_command='sysupgrade -n {remote_path}',
            firmware_rollback_command=firmware_rollback_command, version_parser='openwrt-ubus',
        )

@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    device_id: str
    model: str
    device_type: str
    firmware_version: str
    host: str
    capabilities: DeviceCapabilities
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {'device_id': self.device_id, 'model': self.model, 'device_type': self.device_type,
                'firmware_version': self.firmware_version, 'host': self.host,
                'capabilities': self.capabilities.as_dict(), 'observed_at': self.observed_at.isoformat()}

@dataclass(frozen=True, slots=True)
class DeviceHealth:
    device_id: str
    healthy: bool
    summary: str
    details: Mapping[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class DeviceAdapter(Protocol):
    profile: DeviceProfile
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def health(self) -> DeviceHealth: ...
    def diagnostics(self) -> Mapping[str, Any]: ...
    def capabilities(self) -> DeviceCapabilities: ...
    def version(self) -> DeviceIdentity: ...
    def execute(self, command: str) -> CommandResult: ...
    def execute_shell(self, command: str) -> CommandResult: ...
    def wifi_state(self) -> CommandResult: ...
    def network_state(self) -> CommandResult: ...
    def reboot(self, *, authorization: Any) -> CommandResult: ...
    def upload(self, local_path: str | Path, remote_path: str) -> str: ...

class SSHDeviceAdapter:
    def __init__(self, profile: DeviceProfile, command_runner: CommandRunner) -> None:
        self.profile = profile
        self.command_runner = command_runner

    def connect(self) -> None:
        result = self.execute(self.profile.health_command)
        if not result.transport_succeeded or result.exit_code not in (None, 0):
            raise DeviceUnavailableError(f'device {self.profile.device_id} is unavailable: {result.transport_error or result.stderr or result.stdout}')

    def disconnect(self) -> None: return None

    def health(self) -> DeviceHealth:
        result = self.execute(self.profile.health_command)
        healthy = result.transport_succeeded and result.exit_code in (None, 0)
        return DeviceHealth(self.profile.device_id, healthy,
            f'{self.profile.device_id} health command ' + ('succeeded' if healthy else 'failed'),
            {'stdout': result.stdout[-1000:], 'stderr': result.stderr[-1000:], 'transport_error': result.transport_error})

    def diagnostics(self) -> Mapping[str, Any]:
        output = {}
        for name, command in {'health': self.profile.health_command, 'version': self.profile.version_command,
                              'network': self.profile.network_state_command}.items():
            result = self.execute(command)
            output[name] = {'exit_code': result.exit_code, 'stdout': result.stdout,
                            'stderr': result.stderr, 'transport_error': result.transport_error}
        return output

    def capabilities(self) -> DeviceCapabilities: return self.profile.capabilities

    def version(self) -> DeviceIdentity:
        result = self.execute(self.profile.version_command)
        if not result.transport_succeeded or result.exit_code not in (None, 0):
            raise DeviceUnavailableError(
                f'device version query failed: {result.transport_error or result.stderr or result.stdout}'
            )
        version = self._parse_version(result.stdout)
        if not version:
            raise DeviceAdapterError(f'device {self.profile.device_id} returned no parseable firmware version')
        return DeviceIdentity(self.profile.device_id, self.profile.model, self.profile.device_type,
                              version, self.profile.host, self.profile.capabilities)

    def execute(self, command: str) -> CommandResult:
        return self.command_runner.execute(self.profile.device_id, command, command_category='device', idempotent=True)

    def execute_shell(self, command: str) -> CommandResult:
        return self.command_runner.execute_shell(self.profile.device_id, command, command_category='device_shell', idempotent=False)

    def wifi_state(self) -> CommandResult:
        return self.command_runner.execute(self.profile.device_id, self.profile.wifi_state_command, command_category='wifi_state', idempotent=True)

    def network_state(self) -> CommandResult:
        return self.command_runner.execute(self.profile.device_id, self.profile.network_state_command, command_category='network_state', idempotent=True)

    def reboot(self, *, authorization: Any) -> CommandResult:
        if not getattr(authorization, 'authorized', False) or getattr(authorization, 'operation', '') != 'REBOOT':
            raise PermissionError('explicit REBOOT authorization is required')
        if not self.profile.capabilities.supports_reboot:
            raise DeviceCapabilityError(f'device {self.profile.device_id} does not support reboot')
        return self.command_runner.execute(self.profile.device_id, self.profile.reboot_command, command_category='device_reboot', idempotent=False)

    def upload(self, local_path: str | Path, remote_path: str) -> str:
        source = Path(local_path)
        if not source.is_file(): raise FileNotFoundError(source)
        root = self.profile.remote_firmware_directory.rstrip("/")
        normalized_remote = posixpath.normpath(remote_path)
        if (
            not isinstance(remote_path, str)
            or not _REMOTE_PATH_RE.fullmatch(normalized_remote)
            or ".." in remote_path.split("/")
            or not normalized_remote.startswith(root + "/")
        ):
            raise ValueError("remote firmware path must stay beneath the configured firmware directory")
        remote_path = normalized_remote
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(hostname=self.profile.host, port=self.profile.port, username=self.profile.username,
                           password=self.profile.password, key_filename=self.profile.key_filename,
                           look_for_keys=False, allow_agent=False, timeout=10, auth_timeout=10, banner_timeout=10)
            sftp = client.open_sftp()
            try:
                directory = posixpath.dirname(remote_path)
                current = ""
                for component in directory.strip("/").split("/"):
                    current += "/" + component
                    try:
                        sftp.stat(current)
                    except OSError:
                        if not current.startswith("/tmp/"):
                            raise
                        sftp.mkdir(current)
                sftp.put(str(source), remote_path)
            finally: sftp.close()
        except (OSError, paramiko.SSHException) as exc:
            raise DeviceAdapterError(f'SFTP upload failed for {self.profile.device_id}: {exc}') from exc
        finally:
            client.close()
        return hashlib.sha256(source.read_bytes()).hexdigest()

    def _parse_version(self, output: str) -> str | None:
        if self.profile.version_parser == 'openwrt-ubus':
            try:
                payload = json.loads(output)
            except json.JSONDecodeError:
                return None
            release = payload.get('release', {})
            return str(release.get('version') or release.get('revision') or '').strip() or None
        if self.profile.version_parser == 'regex':
            match = re.search(r'(?im)^\s*version\s*[:=]\s*(\S+)', output)
            return match.group(1) if match else None
        return next((line.strip() for line in output.splitlines() if line.strip()), None)

class OpenWrtDeviceAdapter(SSHDeviceAdapter):
    @classmethod
    def from_profile(cls, profile: DeviceProfile, command_runner: CommandRunner) -> 'OpenWrtDeviceAdapter':
        if profile.device_type.lower() != 'openwrt': raise ValueError('OpenWrtDeviceAdapter requires an openwrt profile')
        return cls(profile, command_runner)

class VirtualLinuxDeviceAdapter(SSHDeviceAdapter):
    @classmethod
    def from_profile(cls, profile: DeviceProfile, command_runner: CommandRunner) -> 'VirtualLinuxDeviceAdapter':
        if profile.device_type.lower() not in {'linux', 'virtual_linux'}: raise ValueError('VirtualLinuxDeviceAdapter requires a Linux profile')
        return cls(profile, command_runner)