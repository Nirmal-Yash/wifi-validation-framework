from __future__ import annotations

import json
import socket
import subprocess
import time


def run_ns(ns: str, *args: str, check: bool = False, capture: bool = False):
    return subprocess.run(["sudo", "ip", "netns", "exec", ns, *args], check=check, capture_output=capture, text=True)


def wait_for_port(ns: str, host: str, port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        probe = run_ns(ns, "bash", "-c", f"</dev/tcp/{host}/{port}", check=False)
        if probe.returncode == 0:
            return
        time.sleep(0.1)
    raise AssertionError(f"iperf3 server did not become ready on {host}:{port}")


def test_data_plane_throughput(system_config, test_params):
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    minimum_mbps = float(test_params["thresholds"]["minimum_throughput_mbps"])

    addr_out = run_ns(client["namespace"], "ip", "-4", "addr", "show", "dev", client["interface"], capture=True).stdout
    if "inet 192.168.50." not in addr_out:
        run_ns(client["namespace"], "dhclient", "-1", "-v", client["interface"], check=True, capture=True)
        addr_out = run_ns(client["namespace"], "ip", "-4", "addr", "show", "dev", client["interface"], capture=True).stdout
    assert "inet 192.168.50." in addr_out, "Client did not obtain a 192.168.50.x address"

    server = subprocess.Popen(
        ["sudo", "ip", "netns", "exec", ap["namespace"], "iperf3", "-s"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_port(client["namespace"], "192.168.50.1", 5201)
        result = run_ns(
            client["namespace"],
            "iperf3", "-c", "192.168.50.1", "-t", "3", "-J",
            check=False,
            capture=True,
        )
        assert result.returncode == 0, f"iperf3 client failed: {result.stderr or result.stdout}"
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"iperf3 returned invalid JSON: {result.stdout[:1000]}") from exc

        end = payload.get("end", {})
        summary = end.get("sum_received") or end.get("sum") or {}
        bits_per_second = float(summary.get("bits_per_second", 0.0))
        measured_mbps = bits_per_second / 1_000_000
        assert measured_mbps >= minimum_mbps, (
            f"Throughput {measured_mbps:.2f} Mbps is below configured minimum "
            f"{minimum_mbps:.2f} Mbps"
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=2)
