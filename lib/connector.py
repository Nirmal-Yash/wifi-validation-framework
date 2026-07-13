import os
from pathlib import Path

import yaml
from netmiko import ConnectHandler

CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "devices.yaml"

_pool = None


def load_devices():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)["devices"]


class ConnectionPool:
    """Reuse SSH sessions across tests in a single pytest session."""

    def __init__(self):
        self._connections = {}
        self._devices = load_devices()

    def get_connection(self, device_name):
        if device_name not in self._connections:
            dev = self._devices[device_name].copy()
            self._connections[device_name] = ConnectHandler(**dev)
        return self._connections[device_name]

    def send_command(self, device_name, command):
        conn = self.get_connection(device_name)
        return conn.send_command(command)

    def send_config_set(self, device_name, commands):
        conn = self.get_connection(device_name)
        return conn.send_config_set(commands)

    def close_all(self):
        for conn in self._connections.values():
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


def ssh_command(device_name, command, pool=None):
    if pool is not None:
        return pool.send_command(device_name, command)
    devices = load_devices()
    conn = ConnectHandler(**devices[device_name])
    try:
        return conn.send_command(command)
    finally:
        conn.disconnect()


def ssh_config(device_name, commands, pool=None):
    if pool is not None:
        return pool.send_config_set(device_name, commands)
    devices = load_devices()
    conn = ConnectHandler(**devices[device_name])
    try:
        return conn.send_config_set(commands)
    finally:
        conn.disconnect()
