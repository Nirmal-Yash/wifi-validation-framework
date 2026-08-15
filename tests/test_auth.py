from __future__ import annotations

import subprocess
import time
from pathlib import Path


def ns_kill(ns: str, process: str) -> None:
    subprocess.run(["sudo", "ip", "netns", "exec", ns, "pkill", "-x", process], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_wpa3_sae_association(system_config, test_params, async_sniffer):
    """Switch the shared radio pair to WPA3-SAE and validate a real SAE association."""
    root = Path(__file__).resolve().parents[1]
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    ap_conf = root / "config" / "wpa3_ap.conf"
    client_conf = root / "config" / "wpa3_client.conf"

    ap_conf.write_text(
        f"""ctrl_interface=/run/hostapd
interface={ap['interface']}
driver=nl80211
ssid=NetForge_WPA3
hw_mode=g
channel=6
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=SAE
rsn_pairwise=CCMP
ieee80211w=2
sae_password=Password123!
sae_pwe=2
""",
        encoding="utf-8",
    )
    client_conf.write_text(
        """ctrl_interface=/run/wpa_supplicant
update_config=0
network={
    ssid=\"NetForge_WPA3\"
    key_mgmt=SAE
    psk=\"Password123!\"
    ieee80211w=2
    scan_ssid=1
}
""",
        encoding="utf-8",
    )

    ns_kill(ap["namespace"], "hostapd")
    ns_kill(client["namespace"], "wpa_supplicant")
    ap_proc = subprocess.Popen(
        ["sudo", "ip", "netns", "exec", ap["namespace"], "hostapd", "-dd", str(ap_conf)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = subprocess.run(["sudo", "ip", "netns", "exec", ap["namespace"], "hostapd_cli", "-i", ap["interface"], "status"], capture_output=True, text=True, check=False)
            if result.returncode == 0 and "state=ENABLED" in result.stdout:
                break
            if ap_proc.poll() is not None:
                stderr = ap_proc.stderr.read() if ap_proc.stderr else ""
                raise AssertionError(f"WPA3 hostapd failed:\n{stderr[-3000:]}")
            time.sleep(0.25)
        else:
            raise AssertionError("WPA3 hostapd did not reach ENABLED state")

        subprocess.run(["sudo", "ip", "netns", "exec", client["namespace"], "ip", "link", "set", client["interface"], "up"], check=True)
        subprocess.run(["sudo", "ip", "netns", "exec", client["namespace"], "wpa_supplicant", "-B", "-Dnl80211", f"-i{client['interface']}", f"-c{client_conf}"], check=True)
        deadline = time.monotonic() + test_params["timeouts"].get("wpa_association_seconds", 20)
        status = ""
        while time.monotonic() < deadline:
            result = subprocess.run(["sudo", "ip", "netns", "exec", client["namespace"], "wpa_cli", "-i", client["interface"], "status"], capture_output=True, text=True, check=False)
            status = result.stdout
            if "wpa_state=COMPLETED" in status:
                break
            time.sleep(0.5)
        assert "wpa_state=COMPLETED" in status, f"WPA3-SAE association did not complete:\n{status}"
    finally:
        ns_kill(client["namespace"], "wpa_supplicant")
        if ap_proc.poll() is None:
            ap_proc.terminate()
            try:
                ap_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                ap_proc.kill()
