import yaml
from netmiko import ConnectHandler

def load_devices():
    with open("configs/devices.yaml") as f:
        return yaml.safe_load(f)["devices"]

def ssh_command(device_name, command):
    devices = load_devices()
    dev = devices[device_name]
    conn = ConnectHandler(**dev)
    output = conn.send_command(command)
    conn.disconnect()
    return output

def ssh_config(device_name, commands):
    devices = load_devices()
    dev = devices[device_name]
    conn = ConnectHandler(**dev)
    output = conn.send_config_set(commands)
    conn.disconnect()
    return output
