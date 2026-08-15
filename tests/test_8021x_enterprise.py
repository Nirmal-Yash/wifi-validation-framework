from __future__ import annotations

import subprocess
import time
from pathlib import Path


def ns_kill(ns: str, process: str) -> None:
    subprocess.run(
        ["sudo", "ip", "netns", "exec", ns, "pkill", "-TERM", "-x", process],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.3)
    subprocess.run(
        ["sudo", "ip", "netns", "exec", ns, "pkill", "-KILL", "-x", process],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_ns(ns: str, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sudo", "ip", "netns", "exec", ns, *args],
        check=check,
        capture_output=True,
        text=True,
    )


def test_enterprise_8021x_authentication(system_config):
    """Validate a real WPA-Enterprise PEAP authentication exchange in hwsim."""
    root = Path(__file__).resolve().parents[1]
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    ap_ns = ap["namespace"]
    client_ns = client["namespace"]
    ap_if = ap["interface"]
    client_if = client["interface"]
    ap_conf = root / "config" / "hostapd_enterprise.conf"
    client_conf = root / "config" / "wpa_supplicant_enterprise.conf"
    ctrl = f"/run/wpa_supplicant/{client_if}"

    ns_kill(ap_ns, "hostapd")
    ns_kill(client_ns, "wpa_supplicant")
    run_ns(client_ns, "rm", "-f", ctrl)
    run_ns(client_ns, "ip", "link", "set", client_if, "down", check=True)
    run_ns(client_ns, "ip", "addr", "flush", "dev", client_if, check=True)
    run_ns(client_ns, "ip", "link", "set", client_if, "up", check=True)
    run_ns(ap_ns, "ip", "link", "set", ap_if, "up", check=True)
    run_ns(ap_ns, "ip", "addr", "replace", "192.168.50.1/24", "dev", ap_if, check=True)

    ap_proc = subprocess.Popen(
        ["sudo", "ip", "netns", "exec", ap_ns, "hostapd", "-dd", str(ap_conf)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 8
        ap_log = ""
        while time.monotonic() < deadline:
            if ap_proc.poll() is not None:
                remaining = ap_proc.stdout.read() if ap_proc.stdout else ""
                raise AssertionError(f"hostapd enterprise daemon exited during startup:\n{ap_log}\n{remaining}")
            status = run_ns(ap_ns, "hostapd_cli", "-i", ap_if, "status")
            ap_log += status.stdout + status.stderr
            if "state=ENABLED" in status.stdout:
                break
            time.sleep(0.25)
        else:
            raise AssertionError(f"Enterprise AP did not reach ENABLED state:\n{ap_log[-6000:]}")

        scan = run_ns(client_ns, "iw", "dev", client_if, "scan", "freq", "2437")
        if scan.returncode != 0 or "NetForge_Enterprise" not in scan.stdout:
            raise AssertionError(
                "Enterprise AP was not discoverable on channel 6.\n"
                f"Client scan:\n{scan.stdout[-5000:]}\n{scan.stderr[-3000:]}\n"
                f"AP status:\n{ap_log[-5000:]}"
            )

        wpa_proc = subprocess.Popen(
            [
                "sudo", "ip", "netns", "exec", client_ns,
                "wpa_supplicant", "-B", "-Dnl80211", "-i", client_if,
                "-c", str(client_conf),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 20
            status_text = ""
            while time.monotonic() < deadline:
                status = run_ns(client_ns, "wpa_cli", "-i", client_if, "status")
                status_text = status.stdout
                if "wpa_state=COMPLETED" in status_text:
                    assert "key_mgmt=WPA-EAP" in status_text
                    return
                time.sleep(0.5)
            scan_result = run_ns(client_ns, "iw", "dev", client_if, "scan", "freq", "2437")
            raise AssertionError(
                "WPA-Enterprise PEAP authentication did not complete.\n"
                f"Status:\n{status_text}\n"
                f"Post-failure scan:\n{scan_result.stdout[-5000:]}\n{scan_result.stderr[-2000:]}\n"
                f"AP log:\n{ap_log[-6000:]}"
            )
        finally:
            ns_kill(client_ns, "wpa_supplicant")
            run_ns(client_ns, "rm", "-f", ctrl)
    finally:
        if ap_proc.poll() is None:
            ap_proc.terminate()
            try:
                ap_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                ap_proc.kill()
