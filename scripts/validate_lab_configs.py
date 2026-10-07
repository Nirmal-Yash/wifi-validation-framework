"""Validate or normalize lab YAML configs against wifi_lab_reprovision_robust.sh constants."""
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

FRR_IP = "192.168.122.10"
AP_IP = "192.168.122.20"
CLIENT_WIFI_IP = "192.168.122.30"
CLIENT_MGMT_IP = "10.10.10.30"
MONITOR_IP = "192.168.122.40"
SSID = "TestNet_5G"
WIFI_PSK = "Test@12345"
MGMT_GW = "10.10.10.1"
LAB_GW = "192.168.122.1"

REQUIRED_DEVICES = {
    "router1": {"host": FRR_IP, "username": "admin", "device_type": "linux", "port": 22},
    "ap_host": {"host": AP_IP, "username": "admin", "device_type": "linux", "port": 22},
    "client_vm": {"host": CLIENT_MGMT_IP, "username": "admin", "device_type": "linux", "port": 22},
    "monitor_vm": {"host": MONITOR_IP, "username": "admin", "device_type": "linux", "port": 22},
}
SECRET_VARS = {
    "router1": "WIFI_ROUTER1_PASSWORD",
    "ap_host": "WIFI_AP_HOST_PASSWORD",
    "client_vm": "WIFI_CLIENT_VM_PASSWORD",
    "monitor_vm": "WIFI_MONITOR_VM_PASSWORD",
}
REQUIRED_NETWORK = {
    "router_ip": FRR_IP,
    "client_interface": "wlan0",
    "monitor_interface": "eth0",
    "dhcp_subnet": "192.168.122.0/24",
    "client_management_ip": CLIENT_MGMT_IP,
    "client_wifi_ip": CLIENT_WIFI_IP,
    "ap_ip": AP_IP,
    "monitor_ip": MONITOR_IP,
    "management_gateway": MGMT_GW,
    "lab_gateway": LAB_GW,
}


def load_yaml(path):
    p = Path(path)
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def validate():
    errs = []
    d = load_yaml(ROOT / "configs/devices.yaml") or {}
    dev = d.get("devices") or {}
    for name, req in REQUIRED_DEVICES.items():
        cur = dev.get(name) or {}
        for k, v in req.items():
            if str(cur.get(k)) != str(v):
                errs.append(f"devices.{name}.{k}: have {cur.get(k)!r} want {v!r}")
        secret_var = SECRET_VARS[name]
        expected_marker = f"__ENV__:{secret_var}"
        if cur.get("password") != expected_marker:
            errs.append(f"devices.{name}.password: must use {expected_marker!r} (no plaintext secret in tracked config)")
        elif not os.getenv(secret_var):
            errs.append(f"devices.{name}.password: environment variable {secret_var} is not set")

    p = load_yaml(ROOT / "configs/test_params.yaml") or {}
    net = p.get("network") or {}
    wifi = p.get("wifi") or {}
    for k, v in REQUIRED_NETWORK.items():
        if str(net.get(k)) != str(v):
            errs.append(f"network.{k}: have {net.get(k)!r} want {v!r}")
    if wifi.get("ssid") != SSID:
        errs.append("wifi.ssid mismatch")
    expected_psk_marker = "__ENV__:WIFI_TEST_PSK"
    if wifi.get("password") != expected_psk_marker:
        errs.append("wifi.password must use __ENV__:WIFI_TEST_PSK (no plaintext secret in tracked config)")
    elif not os.getenv("WIFI_TEST_PSK"):
        errs.append("wifi.password: environment variable WIFI_TEST_PSK is not set")
    return errs


def normalize():
    p = ROOT / "configs/devices.yaml"
    d = load_yaml(p) or {}
    dev = d.setdefault("devices", {})
    for k, v in REQUIRED_DEVICES.items():
        dev.setdefault(k, {}).update(v)
        dev.setdefault(k, {})["password"] = f"__ENV__:{SECRET_VARS[k]}"
    p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")

    p = ROOT / "configs/test_params.yaml"
    d = load_yaml(p) or {}
    d.setdefault("wifi", {}).update({"ssid": SSID, "password": "__ENV__:WIFI_TEST_PSK", "security": "WPA2"})
    d.setdefault("network", {}).update(REQUIRED_NETWORK)
    p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    print("configs normalized")


def main():
    force = os.environ.get("FORCE_NORMALIZE_CONFIG") == "1"
    errs = validate()
    if errs and force:
        normalize()
        return 0
    if errs:
        print("Config validation failed (use --force-normalize-config to rewrite):", file=sys.stderr)
        for e in errs:
            print(" ", e, file=sys.stderr)
        return 1
    print("configs validated OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
