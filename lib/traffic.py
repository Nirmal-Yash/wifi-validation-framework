import json
import re
import subprocess
from pathlib import Path

import yaml

PARAMS_PATH = Path(__file__).resolve().parent.parent / "configs" / "test_params.yaml"


def load_params():
    with open(PARAMS_PATH) as f:
        return yaml.safe_load(f)


def run_ping(host, count=10):
    result = subprocess.run(
        ["ping", "-c", str(count), host],
        capture_output=True,
        text=True,
    )
    loss_match = re.search(r"(\d+)% packet loss", result.stdout)
    rtt_match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", result.stdout)
    if not rtt_match:
        rtt_match = re.search(r"rtt.*?= ([\d.]+)/", result.stdout)
    return {
        "success": result.returncode == 0,
        "packet_loss_pct": int(loss_match.group(1)) if loss_match else 100,
        "avg_rtt_ms": float(rtt_match.group(1)) if rtt_match else None,
    }


def run_iperf3(server_ip, duration=10):
    result = subprocess.run(
        ["iperf3", "-c", server_ip, "-t", str(duration), "-J"],
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    bps = data["end"]["sum_received"]["bits_per_second"]
    return {"throughput_mbps": round(bps / 1e6, 2)}


def run_iperf3_via_ssh(pool, client_device, server_ip, duration=10):
    cmd = f"iperf3 -c {server_ip} -t {duration} -J"
    output = pool.send_command(client_device, cmd)
    data = json.loads(output)
    bps = data["end"]["sum_received"]["bits_per_second"]
    return {"throughput_mbps": round(bps / 1e6, 2)}


def run_dns_lookup(pool, client_device, hostname):
    output = pool.send_command(client_device, f"nslookup {hostname}")
    resolved = "Address:" in output and "can't find" not in output.lower()
    ip_match = re.search(r"Address:\s*([\d.]+)", output)
    return {
        "success": resolved,
        "output": output,
        "resolved_ip": ip_match.group(1) if ip_match else None,
    }
