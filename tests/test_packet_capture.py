import base64
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
    """Validate a real monitor capture; no synthetic PCAP fallback."""
    monitor_iface = params["network"]["monitor_interface"]
    client_iface = params["network"]["client_interface"]
    remote_pcap = "/tmp/dhcp_test.pcap"
    local_pcap = ROOT / "results" / "captures" / "dhcp_test.pcap"
    local_pcap.parent.mkdir(parents=True, exist_ok=True)

    capture = (
        f"sudo rm -f {remote_pcap}; "
        f"sudo timeout 12 tcpdump -i {monitor_iface} -nn -s0 -w {remote_pcap} "
        f"'udp port 67 or udp port 68' >/tmp/dhcp_capture.log 2>&1 & echo $!"
    )
    pid = connection_pool.send_command("monitor_vm", capture, read_timeout=30).strip()
    # Netmiko may include shell job-control output, e.g. "[1] 3713\n3713".
    assert re.search(r"(?:^|\n|\s)\d+\s*$", pid), (
        f"Could not start tcpdump: {pid!r}"
    )

    time.sleep(1)
    connection_pool.send_command(
        "client_vm",
        f"sudo dhclient -r {client_iface} 2>/dev/null || true; sudo dhclient {client_iface}",
        read_timeout=30,
    )
    for _ in range(12):
        size = connection_pool.send_command(
            "monitor_vm",
            f"sudo stat -c%s {remote_pcap} 2>/dev/null || echo 0",
        ).strip()
        if size.isdigit() and int(size) > 64:
            break
        time.sleep(1)
    else:
        raise AssertionError("Monitor PCAP did not grow to a non-trivial size")

    state = connection_pool.send_command(
        "monitor_vm", f"test -s {remote_pcap} && echo FILE_EXISTS || echo NO_FILE"
    ).strip()
    assert state == "FILE_EXISTS", "Monitor did not create a non-empty real DHCP PCAP"

    transfer_cmd = (
        f'printf "__PCAP_BEGIN__\\n"; '
        f"sudo base64 {remote_pcap}; "
        f'printf "\\n__PCAP_END__\\n"'
    )
    b64 = connection_pool.send_command(
        "monitor_vm",
        transfer_cmd,
        expect_string=r"__PCAP_END__",
        strip_prompt=False,
        read_timeout=30,
    )
    match = re.search(
        r"__PCAP_BEGIN__\r?\n(?P<data>.*?)\r?\n__PCAP_END__",
        b64,
        re.DOTALL,
    )
    assert match, "Could not frame PCAP payload returned by monitor"
    clean = "".join(match.group("data").split())
    try:
        data = base64.b64decode(clean, validate=True)
    except Exception as exc:
        raise AssertionError("Could not decode monitor PCAP") from exc
    assert len(data) > 64, "Decoded monitor PCAP is too small to be real traffic"
    local_pcap.write_bytes(data)

    analysis = analyze_dhcp_sequence(str(local_pcap))
    metric_logger.log(analysis["total_packets"], "packets")
    assert analysis["total_packets"] > 0, f"No DHCP frames in real PCAP: {analysis}"
    assert analysis["has_lease_acquired"], f"Real DHCP capture has no ACK: {analysis['message_counts']}"
