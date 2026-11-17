#!/usr/bin/env python3
"""Plan or explicitly apply the Python-owned protected GNS3 Wi-Fi lab setup.

The command is Linux-only, runs as the normal operator account and preserves
the legacy wifi_lab_reprovision_robust.sh as a fallback. It does not run the
protected pytest suite implicitly.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_local_environment() -> None:
    path = ROOT / ".env"
    if path.is_symlink():
        raise PermissionError(".env must be a regular owner-only file")
    if not path.is_file():
        return
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError(".env permissions must be 0600 before guest passwords are loaded")
    from dotenv import load_dotenv
    load_dotenv(path, override=False)


def _guest_passwords() -> dict[str, str]:
    mapping = {
        "router1": "WIFI_ROUTER1_PASSWORD",
        "ap": "WIFI_AP_HOST_PASSWORD",
        "client": "WIFI_CLIENT_VM_PASSWORD",
        "monitor": "WIFI_MONITOR_VM_PASSWORD",
        "wifi_psk": "WIFI_TEST_PSK",
    }
    values = {key: os.getenv(variable, "") for key, variable in mapping.items()}
    missing = [variable for key, variable in mapping.items() if not values[key]]
    if missing:
        raise ValueError("required protected guest credential variables are missing: " + ", ".join(missing))
    return values


def _build_services(database_path: str | None):
    if platform.system() != "Linux":
        raise RuntimeError("protected GNS3/mac80211_hwsim guest provisioning is Linux-only")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise RuntimeError("run the protected lab command as a normal Linux user, not root")

    from lib.platform import platform_adapter_for
    from lib.repositories import SQLiteDatabase
    from lib.services.credential_vault import CredentialVaultService
    from lib.services.gns3_provider import GNS3ProviderError
    from lib.services.linux_lab_host_bootstrap import LinuxLabHostBootstrapService
    from lib.services.linux_lab_host_network import LinuxLabHostNetworkService
    from lib.services.linux_wifi_guest_provisioning import LinuxWiFiGuestProvisioningService
    from lib.services.wifi_lab_provisioning import WiFiLabProvisioningService

    database = SQLiteDatabase(database_path) if database_path else SQLiteDatabase()
    database.initialize()
    platform_adapter = platform_adapter_for()
    vault = CredentialVaultService(
        database,
        platform_adapter.create_secret_store(),
        secret_provider=platform_adapter.descriptor.family.value,
    )
    gns3 = WiFiLabProvisioningService(database, vault)
    host_network = LinuxLabHostNetworkService()
    host_bootstrap = LinuxLabHostBootstrapService(host_network)
    guests = LinuxWiFiGuestProvisioningService(
        host_network,
        resource_lock_manager=gns3.resource_lock_manager,
    )
    return gns3, host_bootstrap, host_network, guests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-id", required=True, help="Active NetRegress Project/Lab ID bound to GNS3.")
    parser.add_argument("--database", help="Optional SQLite database override.")
    parser.add_argument("--actor", default=os.getenv("USER") or "local-operator")
    parser.add_argument("--action", choices=("plan", "apply"), default="plan")
    parser.add_argument("--ssid", default=os.getenv("NETREGRESS_LAB_SSID", "TestNet_5G"))
    parser.add_argument("--confirm", action="store_true", help="Required with --action apply.")
    args = parser.parse_args(argv)

    if args.action == "apply" and not args.confirm:
        parser.error("--action apply requires --confirm")

    try:
        _load_local_environment()
        gns3, host_bootstrap, host_network, guests = _build_services(args.database)
        host_bootstrap_plan = host_bootstrap.plan()
        gns3_plan = gns3.plan(args.lab_id, actor=args.actor)
        host_plan = None
        guest_plan = None
        if host_bootstrap_plan["libvirt_default_network"]["exists"] is True and host_bootstrap_plan["libvirt_default_network"]["active"]:
            host_plan = host_network.plan()
            if host_bootstrap_plan["docker"]["daemon_ready"] and host_plan.get("can_apply"):
                guest_plan = guests.plan()

        if args.action == "plan":
            print(json.dumps({
                "status": "PLANNED",
                "lab_id": args.lab_id,
                "host_readiness": host_bootstrap_plan,
                "gns3": gns3_plan,
                "host_network": host_plan,
                "guests": guest_plan,
                "next_step": (
                    "Review provider/host/guest state. For an explicit apply, set the "
                    "five WIFI_* credential variables in a 0600 .env or protected "
                    "environment, then rerun with --action apply --confirm."
                ),
                "compatibility": "wifi_lab_reprovision_robust.sh remains available until live-lab parity is accepted.",
            }, indent=2, sort_keys=True))
            return 0 if host_bootstrap_plan.get("can_apply") and gns3_plan.get("can_apply") else 1

        passwords = _guest_passwords()
        if not host_bootstrap_plan.get("can_apply"):
            raise RuntimeError("Linux host readiness preflight contains a conflict")
        if not gns3_plan.get("can_apply"):
            raise RuntimeError("GNS3 provider preflight contains a conflict; host setup was not started")
        host_bootstrap_result = host_bootstrap.apply(confirmed=True)
        # Re-read all provider and guest state after host packages, clock,
        # Docker and libvirt reach their verified postconditions.
        gns3_plan = gns3.plan(args.lab_id, actor=args.actor)
        host_plan = host_network.plan()
        guest_plan = guests.plan()
        if not gns3_plan.get("can_apply"):
            raise RuntimeError("GNS3 provider preflight contains a conflict")
        if not host_plan.get("can_apply") or not guest_plan.get("can_apply"):
            raise RuntimeError("protected host-network or guest preflight contains a conflict")

        gns3_result = gns3.apply(args.lab_id, confirmed=True, actor=args.actor)
        # Re-inspect after GNS3 starts nodes/creates the approved management link.
        guest_plan_after = guests.plan()
        if not guest_plan_after.get("can_apply"):
            raise RuntimeError("Docker/hwsim guest preflight contains a conflict after GNS3 startup")
        guest_result = guests.apply(
            lab_id=args.lab_id,
            actor=args.actor,
            passwords=passwords,
            ssid=args.ssid,
            confirmed=True,
        )
        print(json.dumps({
            "status": "APPLIED",
            "lab_id": args.lab_id,
            "host_readiness": host_bootstrap_result,
            "gns3": gns3_result,
            "guests": guest_result,
            "protected_run": (
                "not started automatically; use the canonical Run/evidence workflow "
                "after reviewing the completed provisioning result"
            ),
            "compatibility": "legacy shell entry point retained as recovery fallback",
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        # Errors are intentionally not rendered verbatim because provider and
        # guest libraries can include remote diagnostic content.
        print(json.dumps({
            "status": "FAILED",
            "error_type": type(exc).__name__,
            "recovery": (
                "Do not blindly rerun after partial changes. Inspect GNS3, Docker, "
                "libvirt, hwsim and guest state, then request a fresh --action plan."
            ),
        }, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
