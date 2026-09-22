import hashlib
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from lib.wifi_analyzer import analyze_dhcp_sequence


@pytest.mark.regression
def test_pcap_contains_dhcp_packets(connection_pool, params, metric_logger):
    """Validate real DHCP traffic at the AP bridge; no synthetic PCAP fallback."""
    capture_device = params["network"].get("capture_device", "ap_host")
    capture_iface = params["network"].get("capture_interface", "br0")
    client_iface = params["network"]["client_interface"]
    remote_pcap = "/tmp/dhcp_test.pcap"
    remote_download = "/tmp/dhcp_test.sftp.pcap"
    remote_pid_file = "/tmp/dhcp_capture.pid"
    local_pcap = ROOT / "results" / "captures" / "dhcp_test.pcap"
    local_pcap.parent.mkdir(parents=True, exist_ok=True)

    capture = (
        f"sudo sh -c 'rm -f {remote_pcap} {remote_pid_file}; "
        f"nohup tcpdump -i {capture_iface} -nn -s0 -U -w {remote_pcap} "
        f"udp port 67 or udp port 68 >/tmp/dhcp_capture.log 2>&1 </dev/null & "
        f"echo $! >{remote_pid_file}'"
    )
    # Launching a background process through a PTY can leave Netmiko's prompt-based
    # send_command waiting for shell markers. Use the timing-based API for this
    # one control command; the tcpdump process itself is fully detached.
    capture_connection = connection_pool.get_connection(capture_device)
    capture_connection.send_command_timing(
        capture, read_timeout=15, last_read=1.0, strip_prompt=False
    )
    pid = connection_pool.send_command(
        capture_device, f"cat {remote_pid_file} 2>/dev/null || true", read_timeout=10
    ).strip()
    assert pid.isdigit(), f"Could not start tcpdump on {capture_device}: {pid!r}"

    try:
        for _ in range(5):
            running = connection_pool.send_command(
                capture_device,
                f"sudo kill -0 {pid} 2>/dev/null && echo RUNNING || echo STOPPED",
                read_timeout=10,
            ).strip()
            if running == "RUNNING":
                break
            time.sleep(1)
        else:
            log = connection_pool.send_command(
                capture_device,
                "sudo tail -n 20 /tmp/dhcp_capture.log 2>/dev/null || true",
                read_timeout=10,
            )
            raise AssertionError(
                f"tcpdump did not stay running on {capture_device}: {log!r}"
            )

        time.sleep(1)
        connection_pool.send_command(
            "client_vm",
            f"sudo dhclient -r {client_iface} 2>/dev/null || true; sudo dhclient {client_iface}",
            read_timeout=30,
        )
    finally:
        connection_pool.send_command(
            capture_device,
            f"if test -f {remote_pid_file}; then "
            f"sudo kill -TERM $(cat {remote_pid_file}) 2>/dev/null || true; "
            f"sleep 1; sudo rm -f {remote_pid_file}; fi",
            read_timeout=15,
        )

    for _ in range(12):
        size = connection_pool.send_command(
            capture_device,
            f"sudo stat -c%s {remote_pcap} 2>/dev/null || echo 0",
        ).strip()
        if size.isdigit() and int(size) > 64:
            break
        time.sleep(1)
    else:
        log = connection_pool.send_command(
            capture_device,
            "sudo tail -n 20 /tmp/dhcp_capture.log 2>/dev/null || true",
            read_timeout=10,
        )
        raise AssertionError(
            f"AP PCAP did not grow to a non-trivial size: {log!r}"
        )

    state = connection_pool.send_command(
        capture_device, f"test -s {remote_pcap} && echo FILE_EXISTS || echo NO_FILE"
    ).strip()
    assert state == "FILE_EXISTS", "AP bridge did not create a non-empty real DHCP PCAP"

    # The existing Netmiko command channel is text/prompt oriented; do not use it
    # as a binary transport. Copy the AP capture to a readable temporary path
    # and retrieve the bytes over the authenticated SSH session's SFTP channel.
    local_pcap.unlink(missing_ok=True)
    try:
        connection_pool.send_command(
            capture_device,
            f"sudo cp -- {remote_pcap} {remote_download} && sudo chmod 0644 {remote_download}",
            read_timeout=30,
        )

        connection = connection_pool.get_connection(capture_device)
        with connection.remote_conn_pre.open_sftp() as sftp:
            sftp.get(remote_download, str(local_pcap))

        remote_sha256 = connection_pool.send_command(
            capture_device, f"sha256sum {remote_download}", read_timeout=10
        ).strip()
    finally:
        connection_pool.send_command(
            capture_device, f"sudo rm -f {remote_download}", read_timeout=10
        )

    assert local_pcap.is_file(), "SFTP did not create the local PCAP"
    data = local_pcap.read_bytes()
    assert len(data) > 64, "Downloaded monitor PCAP is too small to be real traffic"

    local_sha256 = hashlib.sha256(data).hexdigest()
    remote_match = re.match(r"^([0-9a-fA-F]{64})\s+", remote_sha256)
    assert remote_match, f"Could not read remote PCAP checksum: {remote_sha256!r}"
    assert local_sha256.lower() == remote_match.group(1).lower(), (
        "Downloaded PCAP checksum does not match the monitor copy"
    )

    analysis = analyze_dhcp_sequence(str(local_pcap))
    metric_logger.log(analysis["total_packets"], "packets")
    assert analysis["total_packets"] > 0, f"No DHCP frames in real PCAP: {analysis}"
    assert analysis["has_lease_acquired"], f"Real DHCP capture has no ACK: {analysis['message_counts']}"
