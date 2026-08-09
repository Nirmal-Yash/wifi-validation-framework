# NetForge Physical Topology (Tier 2) Integration Guide

This guide details the procedure for transitioning NetForge from **Tier 1 (Kernel Simulation)** to **Tier 2 (Physical Hardware-in-the-Loop)** execution.

---

## 1. Physical Hardware Requirements & Wiring

1. **Management Network:** Connect the host machine's dedicated Ethernet NIC (`eth0` or `enp3s0`) to an out-of-band management switch servicing the physical lab devices.
2. **Device Console / SSH Access:** Ensure all target routers, switches, and APs are reachable via IP over SSH.
3. **RF / Data Plane Isolation:** Place physical Access Points inside an RF Shield Box connected to programmable RF attenuators (e.g., Mini-Circuits) to prevent environmental RF interference.

---

## 2. Target Device Pre-Requisites

All target physical devices must be pre-configured with a static management IP, SSH enabled, and a privileged user account:

```text
# Example Cisco IOS Pre-Configuration
username admin privilege 15 secret Password123!
ip domain-name netforge.lab
crypto key generate rsa modulus 2048
line vty 0 4
 transport input ssh
 login local

## 3. Configuring NetForge for Tier 2
# Step A: Update config/devices.yaml

Edit config/devices.yaml to switch the environment target to tier2_physical and define your SSH endpoints:
```YAML

target_environment:
  environment_type: "tier2_physical"
  log_directory: "artifacts/pcaps"

nodes:
  ap:
    name: "Cisco_AP_3802"
    namespace: "ap_ns"
    interface: "wlan0"
    config_path: "config/ap.json"
  client:
    name: "Ubuntu_Client_Node"
    namespace: "client_ns"
    interface: "wlan1"
    config_path: "config/client.json"

physical_hardware:
  Cisco_AP_3802:
    device_type: "cisco_ios"
    ip: "10.0.0.50"
    username: "admin"
    password: "Password123!"
    secret: "Password123!"
  Core_Switch_3750:
    device_type: "cisco_s300"
    ip: "10.0.0.1"
    username: "admin"
    password: "Password123!"

```
## 4. Execution Commands

    Verify SSH Connectivity:
    ```Bash

    python3 -c "from engine.hil_abstractor import ExecutionEnvironment; import yaml; cfg=yaml.safe_load(open('config/devices.yaml')); env=ExecutionEnvironment(cfg); print(env.run_command(cfg['nodes']['ap'], 'show version'))"
    ```
    Execute Test Suite in Tier 2 Mode:
   ```Bash

    python3 -m pytest tests/ -v --fw-version=2.0.0-HIL
   ```
    Revert to Tier 1 Simulation:
    Update environment_type in config/devices.yaml back to localized_netns.

