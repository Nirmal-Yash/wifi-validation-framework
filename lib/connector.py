import os
import time
from pathlib import Path

import yaml
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "devices.yaml"

_pool = None


def load_devices():
    """Load devices from YAML and overlay any environment variables."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        devices = yaml.safe_load(f)["devices"]

    for name, dev in devices.items():
        prefix = f"WIFI_{name.upper()}_"
        if os.getenv(prefix + "HOST"):
            dev["host"] = os.getenv(prefix + "HOST")
        if os.getenv(prefix + "USER"):
            dev["username"] = os.getenv(prefix + "USER")
        if os.getenv(prefix + "PASSWORD"):
            dev["password"] = os.getenv(prefix + "PASSWORD")
        if os.getenv(prefix + "PORT"):
            dev["port"] = int(os.getenv(prefix + "PORT"))
    return devices


class ConnectionPool:
    """Robust SSH connection pool with session health-checks, retries, and timeouts."""

    MAX_RETRIES = 3
    RETRY_DELAY = 2

    def __init__(self):
        self._connections = {}
        self._devices = load_devices()

    def get_connection(self, device_name):
        if device_name not in self._devices:
            raise KeyError(f"Device '{device_name}' not configured in devices.yaml")

        conn = self._connections.get(device_name)
        # Health check existing connection: verify prompt responsiveness
        if conn is not None:
            try:
                conn.find_prompt()
            except Exception:
                try:
                    conn.disconnect()
                except Exception:
                    pass
                del self._connections[device_name]
                conn = None

        if conn is None:
            dev = self._devices[device_name].copy()
            dev.setdefault("conn_timeout", 10)
            dev.setdefault("auth_timeout", 10)
            dev.setdefault("fast_cli", True)

            last_error = None
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    conn = ConnectHandler(**dev)
                    self._connections[device_name] = conn
                    break
                except (NetmikoTimeoutException, NetmikoAuthenticationException, Exception) as err:
                    last_error = err
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY * attempt)

            if conn is None:
                raise ConnectionError(
                    f"Failed to connect to device '{device_name}' at {dev.get('host')} "
                    f"after {self.MAX_RETRIES} attempts: {last_error}"
                ) from last_error

        return conn

    def send_command(self, device_name, command, **kwargs):
        conn = self.get_connection(device_name)
        return conn.send_command(command, **kwargs)

    def send_config_set(self, device_name, commands, **kwargs):
        conn = self.get_connection(device_name)
        return conn.send_config_set(commands, **kwargs)

    def close_all(self):
        for conn in list(self._connections.values()):
            try:
                conn.disconnect()
            except Exception:
                pass
        self._connections.clear()


def get_pool():
    global _pool
    if _pool is None:
        _pool = ConnectionPool()
    return _pool


def reset_pool():
    global _pool
    if _pool is not None:
        _pool.close_all()
        _pool = None


def ssh_command(device_name, command, pool=None, **kwargs):
    if pool is not None:
        return pool.send_command(device_name, command, **kwargs)
    p = get_pool()
    return p.send_command(device_name, command, **kwargs)


def ssh_config(device_name, commands, pool=None, **kwargs):
    if pool is not None:
        return pool.send_config_set(device_name, commands, **kwargs)
    p = get_pool()
    return p.send_config_set(device_name, commands, **kwargs)
