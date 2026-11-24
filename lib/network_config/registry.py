"""Explicit registry for observed network operating-system compiler adapters."""
from __future__ import annotations

import re
from typing import Mapping

from .adapters import ADAPTERS
from .contracts import AdapterDescriptor, NetworkConfigAdapter


class AdapterResolutionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class NetworkConfigAdapterRegistry:
    """Resolve compilers only from a fresh adapter-observed platform identity."""

    _PLATFORM_MATCHERS = (
        ("linux_frr", re.compile(r"\b(?:linux|ubuntu|debian|red\s*hat)\b.*\b(?:frr|frrouting|free\s*range\s*routing)\b|\b(?:frr|frrouting|free\s*range\s*routing)\b.*\blinux\b", re.I)),
        ("cisco_iosxe", re.compile(r"\b(?:cisco\s*)?(?:ios(?:\s*[-/]?\s*xe)?|ios\s*xe)\b", re.I)),
        ("arista_eos", re.compile(r"\barista\b.*\beos\b|\beos\b.*\barista\b", re.I)),
        ("juniper_junos", re.compile(r"\bjuniper\b.*\bjunos\b|\bjunos\b.*\bjuniper\b", re.I)),
        ("paloalto_panos", re.compile(r"\b(?:palo\s*alto(?:\s*networks)?|pan)\b.*\bpan-?os\b|\bpan-?os\b.*\bpalo\s*alto\b", re.I)),
    )
    _VERSION_RANGES = {
        "linux_frr": (7, 10),
        "cisco_iosxe": (15, 17),
        "arista_eos": (4, 4),
        "juniper_junos": (18, 24),
        "paloalto_panos": (10, 12),
    }
    _VENDOR_TOKENS = {
        "linux_frr": ("linux", "ubuntu", "debian", "red hat", "redhat", "canonical", "rocky"),
        "cisco_iosxe": ("cisco",),
        "arista_eos": ("arista",),
        "juniper_junos": ("juniper",),
        "paloalto_panos": ("palo alto", "paloalto"),
    }

    def __init__(self, adapters: tuple[NetworkConfigAdapter, ...] | None = None):
        entries = tuple(adapters or ADAPTERS)
        self._adapters = {}
        for adapter in entries:
            descriptor = getattr(adapter, "descriptor", None)
            if not isinstance(descriptor, AdapterDescriptor):
                raise TypeError("network configuration adapters require an AdapterDescriptor")
            if descriptor.adapter_id in self._adapters:
                raise ValueError("duplicate network configuration adapter: " + descriptor.adapter_id)
            if not callable(getattr(adapter, "compile_target", None)) or not callable(getattr(adapter, "supported_features", None)):
                raise TypeError("network configuration adapter is missing its typed compiler contract")
            self._adapters[descriptor.adapter_id] = adapter

    def list_descriptors(self) -> list[dict]:
        return [self._adapters[key].descriptor.as_dict() for key in sorted(self._adapters)]

    @staticmethod
    def _major(version: object) -> int:
        match = re.search(r"(?<!\d)(\d{1,2})(?:\.\d+)?", str(version or ""))
        if not match:
            raise AdapterResolutionError("SOFTWARE_VERSION_UNKNOWN", "Observed software version is not a recognized numeric version")
        return int(match.group(1))

    def resolve(
        self, device: Mapping[str, object], report: Mapping[str, object]
    ) -> NetworkConfigAdapter:
        platform = str(report.get("platform") or "").strip()
        matches = [adapter_id for adapter_id, pattern in self._PLATFORM_MATCHERS if pattern.search(platform)]
        if len(matches) != 1:
            raise AdapterResolutionError(
                "OBSERVED_PLATFORM_UNSUPPORTED",
                "Observed platform does not identify exactly one supported compiler adapter",
            )
        adapter_id = matches[0]
        adapter = self._adapters.get(adapter_id)
        if adapter is None:
            raise AdapterResolutionError("ADAPTER_NOT_REGISTERED", "The observed platform adapter is not registered")
        vendor = str(device.get("vendor") or "").strip().casefold()
        allowed = self._VENDOR_TOKENS[adapter_id]
        if not vendor or not any(token in vendor for token in allowed):
            raise AdapterResolutionError(
                "DEVICE_VENDOR_PLATFORM_MISMATCH",
                "Managed Device vendor does not corroborate the adapter-observed platform identity",
            )
        model = str(device.get("model") or "").strip().casefold()
        if adapter_id == "cisco_iosxe" and model and not any(token in model for token in ("ios", "catalyst", "isr", "asr")):
            raise AdapterResolutionError("DEVICE_MODEL_PLATFORM_MISMATCH", "Managed Device model is not identified as Cisco IOS/IOS-XE")
        major = self._major(report.get("software_version"))
        minimum, maximum = self._VERSION_RANGES[adapter_id]
        if not minimum <= major <= maximum:
            raise AdapterResolutionError(
                "SOFTWARE_VERSION_UNSUPPORTED",
                f"Observed major version {major} is outside the tested {adapter.descriptor.supported_versions} range",
            )
        return adapter
