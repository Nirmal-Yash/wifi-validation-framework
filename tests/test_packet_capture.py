import hashlib
import re
import shlex
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

    capture_connection = connection_pool.get_connection(capture_device)

    def ap_exec(command, timeout=20, check=True):
        """Run an AP-side command over a raw SSH exec channel, bypassing shell prompts."""
        stdin, stdout, stderr = capture_connection.remote_conn_pre.exec_command(
            command, timeout=timeout
        )
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        if check and rc != 0:
            raise AssertionError(
                f"AP command failed (rc={rc}): {command!r}; stderr={err.strip()!r}"
            )
        return out, err, rc

    # Keep tcpdump in a dedicated foreground SSH channel. A background child
    # launched from an SSH exec session can be terminated when that session
    # closes, even when wrapped with nohup. The dedicated channel stays alive
    # until the DHCP transaction has completed.
    ap_exec(
        f"sudo -n rm -f {shlex.quote(remote_pcap)} {shlex.quote(remote_pid_file)} "
        f"/tmp/dhcp_capture.log",
        timeout=10,
    )

    capture_cmd = (
        f"sudo -n sh -c "
        f"{shlex.quote('echo $$ > ' + remote_pid_file + '; exec tcpdump -i ' + "
                       capture_iface + " -nn -s0 -U -w " + remote_pcap + " "
                       "'udp port 67 or udp port 68' >/tmp/dhcp_capture.log 2>&1")}"
    )
    capture_stdin, capture_stdout, capture_stderr = (
        capture_connection.remote_conn_pre.exec_command(capture_cmd, timeout=15)
    )

    try:
        for _ in range(10):
            ready, _, _ = ap_exec(
                "grep -q 'listening on ' /tmp/dhcp_capture.log 2>/dev/null && "
                "echo READY || echo NOT_READY",
                timeout=10,
            )
            if ready.strip() == "READY":
                break
            time.sleep(0.5)
        else:
            log, _, _ = ap_exec(
                "cat /tmp/dhcp_capture.log 2>/dev/null || true",
                timeout=10,
                check=False,
            )
            raise AssertionError(
                f"tcpdump did not become ready on {capture_device}: {log!r}"
            )

        pid_output, _, _ = ap_exec(
            f"cat {shlex.quote(remote_pid_file)} 2>/dev/null || true",
            timeout=10,
        )
        pid_match = re.fullmatch(r"\\s*(\\d+)\\s*", pid_output)
        assert pid_match, (
            f"Could not identify tcpdump PID on {capture_device}: {pid_output!r}"
        )
        pid = pid_match.group(1)

        running_output, _, _ = ap_exec(
            f"sudo -n kill -0 {pid} 2>/dev/null && echo RUNNING || echo STOPPED",
            timeout=10,
        )
        assert running_output.strip() == "RUNNING", (
            f"tcpdump exited before DHCP traffic was generated on {capture_device}"
        )

        connection_pool.send_command(
            "client_vm",
            f"sudo dhclient -r {client_iface} 2>/dev/null || true; "
            f"sudo dhclient {client_iface}",
            read_timeout=30,
        )

        # SIGINT lets tcpdump finish normally and flush the pcap cleanly.
        ap_exec(
            f"sudo -n kill -INT {pid}",
            timeout=10,
        )

        capture_stdout.channel.settimeout(15)
        capture_stderr.channel.settimeout(15)
        capture_stdout.read()
        capture_stderr.read()
        capture_rc = capture_stdout.channel.recv_exit_status()
        if capture_rc != 0:
            log, _, _ = ap_exec(
                "cat /tmp/dhcp_capture.log 2>/dev/null || true",
                timeout=10,
                check=False,
            )
            raise AssertionError(
                f"tcpdump exited with rc={capture_rc} on {capture_device}: {log!r}"
            )
    finally:
        # Do not mask the test failure with cleanup errors. All root-owned
        # runtime files are removed through sudo.
        try:
            ap_exec(
                f"sudo -n kill -INT $(cat {shlex.quote(remote_pid_file)}) "
                f"2>/dev/null || true; "
                f"sudo -n rm -f {shlex.quote(remote_pid_file)}",
                timeout=10,
                check=False,
            )
        finally:
            try:
                capture_stdin.close()
            except Exception:
                pass

    for _ in range(12):
        size_output, _, _ = ap_exec(
            f"sudo -n stat -c%s {shlex.quote(remote_pcap)} 2>/dev/null || echo 0",
            timeout=10,
        )
        size = size_output.strip()
        if size.isdigit() and int(size) > 64:
            break
        time.sleep(1)
    else:
        log, _, _ = ap_exec(
            "cat /tmp/dhcp_capture.log 2>/dev/null || true",
            timeout=10,
            check=False,
        )
        raise AssertionError(
            f"AP PCAP did not grow to a non-trivial size: {log!r}"
        )

    state_output, _, _ = ap_exec(
        f"test -s {shlex.quote(remote_pcap)} && echo FILE_EXISTS || echo NO_FILE",
        timeout=10,
    )
    state = state_output.strip()
    assert state == "FILE_EXISTS", (
        "AP bridge did not create a non-empty real DHCP PCAP"
    )

    # Retrieve the binary PCAP over the authenticated SSH session's SFTP channel.
    local_pcap.unlink(missing_ok=True)
    try:
        ap_exec(
            f"sudo -n cp -- {shlex.quote(remote_pcap)} {shlex.quote(remote_download)} "
            f"&& sudo -n chmod 0644 {shlex.quote(remote_download)}",
            timeout=30,
        )

        connection = capture_connection
        with connection.remote_conn_pre.open_sftp() as sftp:
            sftp.get(remote_download, str(local_pcap))

        remote_sha256_output, _, _ = ap_exec(
            f"sha256sum {shlex.quote(remote_download)}", timeout=10
        )
        remote_sha256 = remote_sha256_output.strip()
    finally:
        ap_exec(
            f"sudo -n rm -f {shlex.quote(remote_download)}", timeout=10, check=False
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
