"""Simulate firmware upgrade or regression by applying verified system-level state changes."""

import argparse
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.connector import ssh_command

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"


def load_params():
    with open(CONFIGS_DIR / "test_params.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def restore_environment():
    """Restore network nodes back to clean nominal state."""
    params = load_params()
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    ap_template = env.get_template("hostapd.conf.j2")
    ap_config = ap_template.render(
        interface="wlan0",
        ssid=params["wifi"]["ssid"],
        password=params["wifi"]["password"],
        channel=6,
    )

    print("Restoring clean nominal state across lab devices...")
    # 1. Unblock router DNS / DHCP and restart services
    try:
        ssh_command("router1", "sudo iptables -F 2>/dev/null || true")
        ssh_command("router1", "sudo systemctl restart dnsmasq 2>/dev/null || true")
        print("  [router1] iptables flushed, dnsmasq restarted.")
    except Exception as e:
        print(f"  [router1] Restore notice: {e}")

    # 2. Restore AP hostapd
    try:
        ssh_command("ap_host", f"echo '{ap_config}' | sudo tee /etc/hostapd/hostapd.conf")
        ssh_command("ap_host", "sudo systemctl restart hostapd 2>/dev/null || sudo hostapd /etc/hostapd/hostapd.conf -B")
        print("  [ap_host] Clean hostapd config re-applied and reloaded.")
    except Exception as e:
        print(f"  [ap_host] Restore notice: {e}")


def simulate_upgrade(version="v2.0", bug=None):
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    params = load_params()

    print(f"\nSimulating firmware upgrade to '{version}'" + (f" with deliberate regression: [{bug.upper()}]" if bug else ""))

    # 1. Render hostapd config
    target_ssid = "BrokenSSID_Regressed" if bug == "ssid" else params["wifi"]["ssid"]
    ap_template = env.get_template("hostapd.conf.j2")
    ap_config = ap_template.render(
        interface="wlan0",
        ssid=target_ssid,
        password=params["wifi"]["password"],
        channel=6,
    )

    try:
        ssh_command("ap_host", f"echo '{ap_config}' | sudo tee /etc/hostapd/hostapd.conf")
        ssh_command("ap_host", "sudo systemctl restart hostapd 2>/dev/null || sudo hostapd /etc/hostapd/hostapd.conf -B")
        print(f"  [ap_host] Applied hostapd configuration (SSID='{target_ssid}').")
    except Exception as e:
        print(f"  [ap_host] AP config push notice (lab might be offline): {e}")

    # 2. Inject specific bug on router/services if specified
    if bug == "dns":
        print("  [router1] Injecting DNS regression: blocking UDP/53 outbound and stopping DNS forwarder...")
        try:
            ssh_command("router1", "sudo iptables -I OUTPUT -p udp --dport 53 -j DROP")
            ssh_command("router1", "sudo iptables -I FORWARD -p udp --dport 53 -j DROP")
            ssh_command("router1", "sudo systemctl stop dnsmasq 2>/dev/null || true")
            print("  [router1] DNS service disabled successfully.")
        except Exception as e:
            print(f"  [router1] Notice: {e}")

    elif bug == "dhcp":
        print("  [router1] Injecting DHCP regression: terminating DHCP server and dropping BOOTP traffic...")
        try:
            ssh_command("router1", "sudo iptables -I INPUT -p udp --dport 67:68 -j DROP")
            ssh_command("router1", "sudo systemctl stop dnsmasq 2>/dev/null || sudo pkill -f dnsmasq || true")
            print("  [router1] DHCP server disabled successfully.")
        except Exception as e:
            print(f"  [router1] Notice: {e}")

    elif bug == "latency":
        print("  [router1] Injecting performance regression: adding 150ms latency via tc netem...")
        try:
            ssh_command("router1", "sudo tc qdisc add dev eth0 root netem delay 150ms 10ms")
            print("  [router1] 150ms latency injected.")
        except Exception as e:
            print(f"  [router1] Notice: {e}")

    print(f"Firmware upgrade to '{version}' simulation setup complete.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate firmware upgrade and regression injection")
    parser.add_argument("--version", default="v2.0", help="Target firmware version (e.g. v2.0)")
    parser.add_argument("--bug", choices=["dns", "dhcp", "ssid", "latency"], help="Introduce deliberate regression")
    parser.add_argument("--restore", action="store_true", help="Restore nominal lab configuration")
    args = parser.parse_args()

    if args.restore:
        restore_environment()
    else:
        simulate_upgrade(args.version, args.bug)
