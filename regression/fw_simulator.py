"""Simulate firmware upgrade by pushing modified configs via SSH."""

import argparse
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.connector import ssh_command, ssh_config

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"


def load_params():
    with open(CONFIGS_DIR / "test_params.yaml") as f:
        return yaml.safe_load(f)


def simulate_upgrade(version="v2.0", bug=None):
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    params = load_params()

    dns_enabled = bug != "dns"
    dhcp_enabled = bug != "dhcp"

    router_template = env.get_template("router_config.j2")
    router_config = router_template.render(
        firmware_version=version,
        hostname="frr-router",
        lan_ip="192.168.122.1/24",
        dns_enabled=dns_enabled,
        upstream_dns="8.8.8.8",
        dhcp_enabled=dhcp_enabled,
        dhcp_start="192.168.122.100",
        dhcp_end="192.168.122.200",
    )

    ap_template = env.get_template("hostapd.conf.j2")
    ap_config = ap_template.render(
        interface="wlan0",
        ssid=params["wifi"]["ssid"] if bug != "ssid" else "BrokenSSID",
        password=params["wifi"]["password"],
        channel=6,
    )

    print(f"Simulating firmware upgrade to {version}" + (f" with bug: {bug}" if bug else ""))

    try:
        ssh_config("router1", router_config.strip().split("\n"))
        print("Router config pushed.")
    except Exception as e:
        print(f"Router config push failed (lab may be offline): {e}")

    try:
        ssh_command("ap_host", f"echo '{ap_config}' | sudo tee /etc/hostapd/hostapd.conf")
        ssh_command("ap_host", "sudo systemctl restart hostapd 2>/dev/null || sudo hostapd /etc/hostapd/hostapd.conf -B")
        print("AP config pushed.")
    except Exception as e:
        print(f"AP config push failed (lab may be offline): {e}")

    print(f"Firmware {version} simulation complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate firmware upgrade")
    parser.add_argument("--version", default="v2.0", help="Target firmware version")
    parser.add_argument("--bug", choices=["dns", "dhcp", "ssid"], help="Introduce deliberate bug")
    args = parser.parse_args()
    simulate_upgrade(args.version, args.bug)
