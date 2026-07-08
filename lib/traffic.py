import subprocess, re, yaml

def load_params():
    with open("configs/test_params.yaml") as f:
        return yaml.safe_load(f)

def run_ping(host, count=10):
    result = subprocess.run(
        ["ping", "-c", str(count), host],
        capture_output=True, text=True
    )
    loss_match = re.search(r"(d+)% packet loss", result.stdout)
    rtt_match  = re.search(r"rtt.*?= ([d.]+)/", result.stdout)
    return {
        "success": result.returncode == 0,
        "packet_loss_pct": int(loss_match.group(1)) if loss_match else 100,
        "avg_rtt_ms": float(rtt_match.group(1)) if rtt_match else None
    }

def run_iperf3(server_ip, duration=10):
    result = subprocess.run(
        ["iperf3", "-c", server_ip, "-t", str(duration), "-J"],
        capture_output=True, text=True
    )
    import json
    data = json.loads(result.stdout)
    bps = data["end"]["sum_received"]["bits_per_second"]
    return {"throughput_mbps": round(bps / 1e6, 2)}
