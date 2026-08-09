import subprocess
from netmiko import ConnectHandler

class ExecutionEnvironment:
    def __init__(self, config):
        self.mode = config["target_environment"]["environment_type"]
        self.hardware_nodes = config.get("physical_hardware", {})
        self.active_ssh_sessions = {}

    def get_ssh_connection(self, device_name):
        """Maintains a persistent Netmiko SSH connection pool to physical devices."""
        if device_name not in self.active_ssh_sessions:
            device_info = self.hardware_nodes[device_name]
            connection = ConnectHandler(
                device_type=device_info["device_type"],
                host=device_info["ip"],
                username=device_info["username"],
                password=device_info["password"],
                secret=device_info.get("secret", "")
            )
            connection.enable()
            self.active_ssh_sessions[device_name] = connection
        return self.active_ssh_sessions[device_name]

    def run_command(self, target_node, command):
        """Routes commands to netns (Tier 1) or physical devices via SSH (Tier 2)."""
        if self.mode == "localized_netns":
            # Execute inside the virtual namespace
            full_cmd = f"sudo ip netns exec {target_node['namespace']} {command}"
            result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
            return result.stdout
            
        elif self.mode == "tier2_physical":
            # Execute natively on the physical hardware via SSH
            print(f"[HIL API] Routing command over SSH to {target_node['name']}")
            ssh_conn = self.get_ssh_connection(target_node['name'])
            return ssh_conn.send_command(command)

    def close_all_sessions(self):
        """Gracefully tears down physical SSH sessions."""
        for name, session in self.active_ssh_sessions.items():
            session.disconnect()
