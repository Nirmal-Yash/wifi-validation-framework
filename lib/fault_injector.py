import contextlib
import subprocess


def _exec(cmd, pool=None, device=None, check=True):
    """Execute command either remotely via SSH pool or locally via subprocess."""
    if pool is not None and device is not None:
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        return pool.send_command(device, cmd_str)

    if isinstance(cmd, str):
        cmd_list = cmd.split()
    else:
        cmd_list = cmd
    return subprocess.run(cmd_list, check=check, capture_output=True, text=True)


def link_down(interface, pool=None, device=None):
    """Set network link down."""
    cmd = ["sudo", "ip", "link", "set", interface, "down"]
    return _exec(cmd, pool, device, check=True)


def link_up(interface, pool=None, device=None):
    """Set network link up."""
    cmd = ["sudo", "ip", "link", "set", interface, "up"]
    return _exec(cmd, pool, device, check=True)


def add_delay(interface, delay_ms=100, jitter_ms=0, pool=None, device=None):
    """Inject latency (and optional jitter) via tc netem."""
    clear_conditions(interface, pool, device)
    cmd = ["sudo", "tc", "qdisc", "add", "dev", interface, "root", "netem", "delay", f"{delay_ms}ms"]
    if jitter_ms > 0:
        cmd.extend([f"{jitter_ms}ms", "distribution", "normal"])
    return _exec(cmd, pool, device, check=True)


def add_packet_loss(interface, loss_pct=10, pool=None, device=None):
    """Inject packet loss percentage via tc netem."""
    clear_conditions(interface, pool, device)
    cmd = ["sudo", "tc", "qdisc", "add", "dev", interface, "root", "netem", "loss", f"{loss_pct}%"]
    return _exec(cmd, pool, device, check=True)


def add_bandwidth_limit(interface, rate_kbit=1000, pool=None, device=None):
    """Throttle interface bandwidth via token bucket filter (tbf)."""
    clear_conditions(interface, pool, device)
    cmd = [
        "sudo",
        "tc",
        "qdisc",
        "add",
        "dev",
        interface,
        "root",
        "tbf",
        "rate",
        f"{rate_kbit}kbit",
        "burst",
        "32kbit",
        "latency",
        "400ms",
    ]
    return _exec(cmd, pool, device, check=True)


def clear_conditions(interface, pool=None, device=None):
    """Remove any traffic control / netem qdisc on the interface."""
    cmd = ["sudo", "tc", "qdisc", "del", "dev", interface, "root"]
    return _exec(cmd, pool, device, check=False)


# ─── Service-level Faults ──────────────────────────────────────────────────


def block_dns(pool=None, device=None):
    """Block outgoing DNS UDP/53 queries using iptables."""
    cmd = "sudo iptables -I OUTPUT -p udp --dport 53 -j DROP"
    return _exec(cmd, pool, device, check=False)


def unblock_dns(pool=None, device=None):
    """Remove DNS blocking iptables rule."""
    cmd = "sudo iptables -D OUTPUT -p udp --dport 53 -j DROP 2>/dev/null || true"
    return _exec(cmd, pool, device, check=False)


def stop_dhcp_server(pool=None, device=None):
    """Stop DHCP server service (dnsmasq or isc-dhcp-server)."""
    cmd = "sudo systemctl stop dnsmasq 2>/dev/null || sudo pkill -f dnsmasq || true"
    return _exec(cmd, pool, device, check=False)


def start_dhcp_server(pool=None, device=None):
    """Start DHCP server service."""
    cmd = "sudo systemctl start dnsmasq 2>/dev/null || sudo dnsmasq || true"
    return _exec(cmd, pool, device, check=False)


@contextlib.contextmanager
def fault_context(fault_fn, restore_fn, *args, **kwargs):
    """
    Context manager that applies a fault and guarantees restoration
    even if the test raises an exception or assertion failure.
    """
    fault_fn(*args, **kwargs)
    try:
        yield
    finally:
        restore_fn(*args, **kwargs)
