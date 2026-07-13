import subprocess
import time
from pathlib import Path

import pyshark

CAPTURES_DIR = Path(__file__).resolve().parent.parent / "results" / "captures"


def start_capture(interface, output_file, duration=10):
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(output_file)
    if not out.is_absolute():
        out = CAPTURES_DIR / out
    proc = subprocess.Popen(
        ["tcpdump", "-i", interface, "-w", str(out), "-G", str(duration), "-W", "1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(duration + 1)
    proc.terminate()
    return str(out)


def read_pcap(filepath):
    cap = pyshark.FileCapture(filepath)
    packets = [pkt for pkt in cap]
    cap.close()
    return packets


def filter_pcap(filepath, display_filter):
    cap = pyshark.FileCapture(filepath, display_filter=display_filter)
    packets = [pkt for pkt in cap]
    cap.close()
    return packets


def count_dhcp_packets(filepath):
    try:
        packets = filter_pcap(filepath, "bootp")
        return len(packets)
    except Exception:
        return 0
