from __future__ import annotations

import subprocess
import time
from pathlib import Path


def ns_kill(ns: str, process: str) -> None:
    subprocess.run(
        ["sudo", "ip", "netns", "exec", ns, "pkill", "-x", process],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_enterprise_8021x_authentication(system_config):
    """Validate a real WPA-Enterprise PEAP authentication exchange in hwsim."""
    root = Path(__file__).resolve().parents[1]
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    ap_conf = root / "config" / "hostapd_enterprise.conf"
    client_conf = root / "config" / "wpa_supplicant_enterprise.conf"

    ns_kill(ap["namespace"], "hostapd")
    ns_kill(client["namespace"], "wpa_supplicant")
    ap_proc = subprocess.Popen(
        ["sudo", "ip", "netns", "exec", ap["namespace"], "hostapd", str(ap_conf)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(2)
        if ap_proc.poll() is not None:
            stderr = ap_proc.stderr.read() if ap_proc.stderr else ""
            raise AssertionError(f"hostapd enterprise daemon exited during startup: {stderr[-3000:]}")

        subprocess.run(
            ["sudo", "ip", "netns", "exec", client["namespace"], "ip", "link", "set", client["interface"], "up"],
            check=True,
        )
        subprocess.run(
            ["sudo", "ip", "netns", "exec", client["namespace"], "wpa_supplicant", "-B", "-i", client["interface"], "-c", str(client_conf)],
            check=True,
        )
        deadline = time.monotonic() + 15
        status = ""
        while time.monotonic() < deadline:
            result = subprocess.run(
                ["sudo", "ip", "netns", "exec", client["namespace"], "wpa_cli", "-i", client["interface"], "status"],
                capture_output=True,
                text=True,
                check=False,
            )
            status = result.stdout
            if "wpa_state=COMPLETED" in status:
                break
            time.sleep(0.5)
        assert "wpa_state=COMPLETED" in status, f"WPA-Enterprise authentication did not complete:\n{status}"
    finally:
        ns_kill(client["namespace"], "wpa_supplicant")
        ap_proc.terminate()
        try:
            ap_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            ap_proc.kill()
