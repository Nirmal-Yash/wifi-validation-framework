from __future__ import annotations

import subprocess
import time
from pathlib import Path


def ns_kill(ns: str, process: str) -> None:
    subprocess.run(["sudo", "ip", "netns", "exec", ns, "pkill", "-TERM", "-x", process], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    subprocess.run(["sudo", "ip", "netns", "exec", ns, "pkill", "-KILL", "-x", process], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_ns(ns: str, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sudo", "ip", "netns", "exec", ns, *args], check=check, capture_output=True, text=True)


def wpa_cli(ns: str, interface: str, *args: str) -> subprocess.CompletedProcess[str]:
    return run_ns(ns, "wpa_cli", "-p", "/run/wpa_supplicant", "-i", interface, *args)


def wait_wpa_control(ns: str, interface: str, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        result = wpa_cli(ns, interface, "ping")
        last = result.stdout or result.stderr
        if result.returncode == 0 and "PONG" in result.stdout:
            return
        time.sleep(0.2)
    raise AssertionError(f"wpa_supplicant control interface did not become ready:\n{last}")


def wait_enterprise(ns: str, interface: str, log_path: Path, timeout: float = 30) -> str:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        result = wpa_cli(ns, interface, "status")
        last = result.stdout or result.stderr
        if result.returncode == 0 and "wpa_state=COMPLETED" in result.stdout:
            return result.stdout
        time.sleep(0.5)
    log = log_path.read_text(encoding="utf-8", errors="replace")[-12000:] if log_path.exists() else ""
    raise AssertionError(f"WPA-Enterprise PEAP authentication did not complete.\nStatus:\n{last}\nwpa_supplicant log:\n{log}")


def test_enterprise_8021x_authentication(system_config):
    """Validate real WPA-Enterprise PEAP/MSCHAPv2 authentication in hwsim."""
    root = Path(__file__).resolve().parents[1]
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    ap_ns, client_ns = ap["namespace"], client["namespace"]
    ap_if, client_if = ap["interface"], client["interface"]
    ap_conf = root / "config" / "hostapd_enterprise.conf"
    client_conf = root / "config" / "wpa_supplicant_enterprise.conf"
    ctrl = f"/run/wpa_supplicant/{client_if}"
    log_dir = root / "artifacts" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ap_log = log_dir / "enterprise-hostapd.log"
    wpa_log = log_dir / "enterprise-wpa.log"
    ap_log.unlink(missing_ok=True)
    wpa_log.unlink(missing_ok=True)

    ns_kill(ap_ns, "hostapd")
    ns_kill(client_ns, "wpa_supplicant")
    run_ns(client_ns, "rm", "-f", ctrl)
    run_ns(ap_ns, "rm", "-f", f"/run/hostapd/{ap_if}")
    run_ns(client_ns, "ip", "link", "set", client_if, "down", check=True)
    run_ns(client_ns, "ip", "addr", "flush", "dev", client_if, check=True)
    run_ns(client_ns, "ip", "link", "set", client_if, "up", check=True)
    run_ns(ap_ns, "ip", "link", "set", ap_if, "down", check=True)
    run_ns(ap_ns, "ip", "addr", "flush", "dev", ap_if, check=True)
    run_ns(ap_ns, "ip", "link", "set", ap_if, "up", check=True)
    run_ns(ap_ns, "ip", "addr", "replace", "192.168.50.1/24", "dev", ap_if, check=True)

    ap_out = ap_log.open("w", encoding="utf-8")
    ap_proc = subprocess.Popen(["sudo", "ip", "netns", "exec", ap_ns, "hostapd", "-dd", str(ap_conf)], cwd=root, stdout=ap_out, stderr=subprocess.STDOUT, text=True)
    wpa_proc = None
    wpa_out = None
    try:
        deadline = time.monotonic() + 10
        ap_status = ""
        while time.monotonic() < deadline:
            if ap_proc.poll() is not None:
                break
            result = run_ns(ap_ns, "hostapd_cli", "-p", "/run/hostapd", "-i", ap_if, "status")
            ap_status = result.stdout or result.stderr
            if "state=ENABLED" in result.stdout:
                break
            time.sleep(0.25)
        if ap_proc.poll() is not None or "state=ENABLED" not in ap_status:
            log = ap_log.read_text(encoding="utf-8", errors="replace")[-12000:]
            raise AssertionError(f"Enterprise AP did not reach ENABLED state.\nStatus:\n{ap_status}\nHostapd log:\n{log}")

        scan = run_ns(client_ns, "iw", "dev", client_if, "scan", "freq", "2437")
        if scan.returncode != 0 or "SSID: NetForge_Enterprise" not in scan.stdout:
            raise AssertionError(f"Enterprise AP was not discoverable on channel 6:\n{scan.stdout[-6000:]}\n{scan.stderr[-3000:]}")

        wpa_out = wpa_log.open("w", encoding="utf-8")
        wpa_proc = subprocess.Popen(["sudo", "ip", "netns", "exec", client_ns, "wpa_supplicant", "-dd", "-Dnl80211", f"-i{client_if}", "-C/run/wpa_supplicant", f"-c{client_conf}"], cwd=root, stdout=wpa_out, stderr=subprocess.STDOUT, text=True)
        wait_wpa_control(client_ns, client_if)

        networks = wpa_cli(client_ns, client_if, "list_networks")
        if networks.returncode != 0:
            raise AssertionError(f"wpa_cli list_networks failed:\n{networks.stdout}\n{networks.stderr}")
        network_id = next((line.split("\t", 1)[0] for line in networks.stdout.splitlines()[1:] if len(line.split("\t")) >= 2 and line.split("\t")[1] == "NetForge_Enterprise"), None)
        if network_id is None:
            raise AssertionError(f"NetForge_Enterprise was not loaded by wpa_supplicant:\n{networks.stdout}")

        for command in (("disable_network", network_id), ("enable_network", network_id), ("select_network", network_id), ("reassociate",)):
            result = wpa_cli(client_ns, client_if, *command)
            if result.returncode != 0 or "FAIL" in result.stdout:
                raise AssertionError(f"wpa_cli {' '.join(command)} failed:\n{result.stdout}\n{result.stderr}")

        status = wait_enterprise(client_ns, client_if, wpa_log)
        assert "key_mgmt=WPA-EAP" in status, status
        assert "ssid=NetForge_Enterprise" in status, status
    finally:
        ns_kill(client_ns, "wpa_supplicant")
        ns_kill(ap_ns, "hostapd")
        run_ns(client_ns, "rm", "-f", ctrl)
        if wpa_proc and wpa_proc.poll() is None:
            wpa_proc.kill()
        if ap_proc.poll() is None:
            ap_proc.kill()
        if wpa_out:
            wpa_out.close()
        ap_out.close()
