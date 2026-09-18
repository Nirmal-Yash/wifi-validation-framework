import json
import re
import subprocess
from pathlib import Path

import yaml

PARAMS_PATH = Path(__file__).resolve().parent.parent / "configs" / "test_params.yaml"


def load_params():
    with open(PARAMS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_ping(host, count=10, timeout=30):
    """Execute ping command and parse packet loss and RTT statistics robustly."""
    try:
        # Check platform to support both Linux and Windows environments
        import platform

        is_win = platform.system().lower() == "windows"
        cmd = ["ping", "-n" if is_win else "-c", str(count), host]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "packet_loss_pct": 100.0,
            "avg_rtt_ms": None,
            "error": "Ping command timed out",
        }
    except Exception as e:
        return {
            "success": False,
            "packet_loss_pct": 100.0,
            "avg_rtt_ms": None,
            "error": str(e),
        }

    # Match packet loss (Linux or Windows style)
    loss_match = re.search(r"(\d+(?:\.\d+)?)%\s*(?:packet\s*)?loss", stdout, re.IGNORECASE)
    packet_loss_pct = float(loss_match.group(1)) if loss_match else (0.0 if result.returncode == 0 else 100.0)

    # Match RTT: Linux "rtt min/avg/max/mdev = 1.1/2.2/3.3/0.4 ms"
    avg_rtt = None
    rtt_match = re.search(r"rtt\s+min/avg/max/(?:mdev|stddev)\s*=\s*[\d.]+/([\d.]+)/", stdout, re.IGNORECASE)
    if not rtt_match:
        # Generic Linux match
        rtt_match = re.search(r"rtt.*?=\s*[\d.]+/([\d.]+)/", stdout, re.IGNORECASE)
    if not rtt_match:
        # Windows match: "Average = 23ms"
        win_match = re.search(r"Average\s*=\s*(\d+)ms", stdout, re.IGNORECASE)
        if win_match:
            avg_rtt = float(win_match.group(1))

    if rtt_match:
        avg_rtt = float(rtt_match.group(1))

    success = result.returncode == 0 and packet_loss_pct < 100.0

    return {
        "success": success,
        "packet_loss_pct": packet_loss_pct,
        "avg_rtt_ms": avg_rtt,
        "stdout": stdout,
    }


def run_iperf3(server_ip, duration=10, timeout=None):
    """Run local iperf3 client with JSON output and rigorous error handling."""
    t_out = timeout or (duration + 15)
    try:
        result = subprocess.run(
            ["iperf3", "-c", server_ip, "-t", str(duration), "-J"],
            capture_output=True,
            text=True,
            timeout=t_out,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"iperf3 to {server_ip} timed out after {t_out} seconds")
    except FileNotFoundError:
        raise RuntimeError("iperf3 binary not found in system PATH")

    if not result.stdout.strip():
        raise RuntimeError(f"iperf3 returned empty output. Stderr: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Failed to parse iperf3 JSON output: {err}\nOutput: {result.stdout[:500]}") from err

    if "error" in data:
        raise RuntimeError(f"iperf3 error reported by server/client: {data['error']}")

    try:
        bps = data["end"]["sum_received"]["bits_per_second"]
    except KeyError:
        # Fallback to sum_sent if sum_received is omitted
        bps = data["end"]["sum_sent"]["bits_per_second"]

    mbps = round(bps / 1e6, 2)
    return {
        "success": True,
        "throughput_mbps": mbps,
        "raw": data.get("end", {}),
    }


def run_iperf3_via_ssh(pool, client_device, server_ip, duration=10):
    """Run iperf3 remotely on client_device over SSH with JSON validation."""
    cmd = f"iperf3 -c {server_ip} -t {duration} -J"
    output = pool.send_command(client_device, cmd)

    if not output or not output.strip():
        raise RuntimeError(f"No response from {client_device} when executing: {cmd}")

    # Extract JSON object from potential SSH banner / motd noise
    json_start = output.find("{")
    json_end = output.rfind("}")
    if json_start == -1 or json_end == -1:
        raise RuntimeError(
            f"Unable to find JSON in iperf3 output from {client_device}. Output: {output[:400]}"
        )

    clean_json = output[json_start : json_end + 1]
    try:
        data = json.loads(clean_json)
    except json.JSONDecodeError as err:
        raise RuntimeError(
            f"Failed to decode iperf3 JSON from {client_device}: {err}. Extracted: {clean_json[:300]}"
        ) from err

    if "error" in data:
        raise RuntimeError(f"iperf3 error on {client_device}: {data['error']}")

    try:
        bps = data["end"]["sum_received"]["bits_per_second"]
    except KeyError:
        bps = data["end"]["sum_sent"]["bits_per_second"]

    mbps = round(bps / 1e6, 2)
    return {
        "success": True,
        "throughput_mbps": mbps,
        "raw": data.get("end", {}),
    }


def run_dns_lookup(pool, client_device, hostname):
    """Perform DNS lookup on remote client device and parse resolved IP."""
    output = pool.send_command(client_device, f"nslookup {hostname}")
    resolved = "Address:" in output and "can't find" not in output.lower() and "server can't find" not in output.lower()

    # Find address lines (avoid loopback if multiple addresses)
    ip_matches = re.findall(r"Address:\s*([\d\.:a-fA-F]+)", output)
    resolved_ip = None
    if ip_matches:
        # If multiple, the first is often the DNS server, subsequent ones are resolved hosts
        resolved_ip = ip_matches[-1] if len(ip_matches) > 1 else ip_matches[0]

    return {
        "success": resolved and (resolved_ip is not None),
        "output": output,
        "resolved_ip": resolved_ip,
    }
