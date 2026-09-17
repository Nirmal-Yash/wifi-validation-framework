import contextlib
import subprocess
import time
from pathlib import Path

try:
    import pyshark
except ImportError:
    pyshark = None

CAPTURES_DIR = Path(__file__).resolve().parent.parent / "results" / "captures"


class AsyncCapture:
    """Non-blocking background packet capture controller using tcpdump."""

    def __init__(self, interface, output_file, duration=None, filter_expr=None):
        CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        out = Path(output_file)
        if not out.is_absolute():
            out = CAPTURES_DIR / out
        self.output_path = out
        self.interface = interface
        self.duration = duration
        self.filter_expr = filter_expr
        self.proc = None
        self._start_time = None

    def start(self):
        cmd = ["tcpdump", "-i", self.interface, "-w", str(self.output_path), "-U"]
        if self.duration:
            cmd.extend(["-G", str(self.duration), "-W", "1"])
        if self.filter_expr:
            cmd.extend(self.filter_expr.split())

        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._start_time = time.time()
        # Allow tcpdump a tiny slice to attach to the socket/interface
        time.sleep(0.3)
        return self

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return str(self.output_path)


@contextlib.contextmanager
def capture_context(interface, output_file, filter_expr=None):
    """Context manager for clean background packet captures."""
    cap = AsyncCapture(interface, output_file, filter_expr=filter_expr)
    cap.start()
    try:
        yield cap
    finally:
        cap.stop()


def start_capture(interface, output_file, duration=10, filter_expr=None):
    """Start capture and return the AsyncCapture handle (non-blocking)."""
    cap = AsyncCapture(interface, output_file, duration=duration, filter_expr=filter_expr)
    cap.start()
    return cap


def read_pcap(filepath):
    """Read packets from pcap file using pyshark."""
    if pyshark is None:
        raise ImportError("pyshark is not installed. Install it via pip install pyshark")
    cap = pyshark.FileCapture(str(filepath))
    try:
        packets = list(cap)
    finally:
        cap.close()
    return packets


def filter_pcap(filepath, display_filter):
    """Filter pcap file using Wireshark display filter."""
    if pyshark is None:
        raise ImportError("pyshark is not installed. Install it via pip install pyshark")
    cap = pyshark.FileCapture(str(filepath), display_filter=display_filter)
    try:
        packets = list(cap)
    finally:
        cap.close()
    return packets


def count_dhcp_packets(filepath):
    """Count BOOTP/DHCP packets in pcap using pyshark, with graceful fallback."""
    if not Path(filepath).exists():
        return 0
    try:
        packets = filter_pcap(filepath, "bootp")
        return len(packets)
    except Exception:
        # Fallback to Scapy if pyshark or tshark is unavailable
        try:
            from scapy.all import DHCP, rdpcap

            pkts = rdpcap(str(filepath))
            return len([p for p in pkts if p.haslayer(DHCP)])
        except Exception:
            return 0
