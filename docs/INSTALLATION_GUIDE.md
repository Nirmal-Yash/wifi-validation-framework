# Installation Guide — WiFi Validation Framework

This document covers **all manual steps** required to set up the virtual lab and development environment on your **Ubuntu 22.04 VM** (running inside VirtualBox). Complete every section in order before running tests.

---

## Table of Contents

1. [Hardware & VM Requirements](#1-hardware--vm-requirements)
2. [Ubuntu 22.04 Base Setup](#2-ubuntu-2204-base-setup)
3. [System Packages](#3-system-packages)
4. [GNS3 Installation](#4-gns3-installation)
5. [Docker Installation](#5-docker-installation)
6. [GNS3 Topology Creation](#6-gns3-topology-creation)
7. [FRR Router Configuration](#7-frr-router-configuration)
8. [hostapd Access Point Setup](#8-hostapd-access-point-setup)
9. [Client VM Setup](#9-client-vm-setup)
10. [Monitor VM Setup](#10-monitor-vm-setup)
11. [Connectivity Verification](#11-connectivity-verification)
12. [Clone Repo & Python Environment](#12-clone-repo--python-environment)
13. [Update Configuration Files](#13-update-configuration-files)
14. [First Test Run](#14-first-test-run)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Hardware & VM Requirements

### Host Machine (Windows + VirtualBox)

| Component | Minimum | Recommended |
|---|---|---|
| RAM | 8 GB total (4 GB for VM) | 16 GB total (8 GB for VM) |
| CPU | 4 cores | 6–8 cores |
| Storage | 50 GB free | 100 GB SSD |

### Ubuntu VM Settings in VirtualBox

1. Open VirtualBox → select your Ubuntu VM → **Settings**
2. **System → Motherboard**: RAM = **4096 MB** minimum (8192 MB recommended)
3. **System → Processor**: CPUs = **2** minimum (4 recommended)
4. **Network → Adapter 1**: Attached to **NAT** or **Bridged Adapter**
5. **Storage**: Ensure virtual disk is at least **40 GB**
6. Start the VM and log in to Ubuntu 22.04

---

## 2. Ubuntu 22.04 Base Setup

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y software-properties-common curl wget git vim net-tools
```

Verify:

```bash
lsb_release -a    # Should show Ubuntu 22.04
python3 --version # Should show 3.10+
```

---

## 3. System Packages

Install all tools needed by the framework and lab:

```bash
sudo apt install -y \
    python3 python3-pip python3-venv \
    wireshark tshark \
    iperf3 tcpdump hping3 \
    openssh-server \
  build-essential libssl-dev \
    bridge-utils iw wpasupplicant hostapd dnsmasq
```

Allow your user to run Wireshark without root:

```bash
sudo usermod -aG wireshark $USER
# Log out and back in for group change to take effect
```

Verify:

```bash
iperf3 --version
tcpdump --version
tshark --version
ssh -V
```

---

## 4. GNS3 Installation

### Option A — Official Installer (Recommended)

1. Download GNS3 from: https://www.gns3.com/software/download
2. Choose **Linux** → download the installer for Ubuntu 22.04
3. Install:

```bash
chmod +x GNS3*.run
sudo ./GNS3*.run
```

### Option B — Via pip

```bash
pip3 install gns3-server gns3-gui
```

### Verify GNS3

```bash
gns3
# GUI should launch
```

In GNS3 GUI:
- Go to **Edit → Preferences → GNS3 VM** → disable GNS3 VM if running locally
- Go to **Edit → Preferences → Dynamips** → verify settings

---

## 5. Docker Installation

GNS3 uses Docker to run FRR router containers.

```bash
# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# Log out and back in

# Verify
docker --version
docker run hello-world
```

### Link Docker with GNS3

1. Open GNS3 → **Edit → Preferences → Docker**
2. Click **New** → select `frrouting/frr` image (pull if not present):

```bash
docker pull frrouting/frr:latest
```

3. Set container name: `FRR-Router`
4. Add environment variable: `FRR_ROUTER1=1`

---

## 6. GNS3 Topology Creation

Create a new GNS3 project: **WiFi-Regression-Lab**

### Nodes to Add

| Node | Type | Image | Management IP |
|---|---|---|---|
| FRR Router | Docker `frrouting/frr` | frr:latest | 192.168.122.10 |
| AP VM | QEMU/Linux | Ubuntu 22.04 | 192.168.122.20 |
| Client VM | QEMU/Linux | Ubuntu 22.04 | 192.168.122.30 |
| Monitor VM | QEMU/Linux | Ubuntu 22.04 | 192.168.122.40 |

### Topology Diagram

```
[FRR Router] ----eth---- [AP VM (hostapd)] ~~~wifi~~~ [Client VM]
      |
      +----eth---- [Monitor VM]
```

### Steps in GNS3

1. **Add FRR Router**: Drag Docker `frrouting/frr` to canvas
2. **Add 3 Linux VMs**: Drag QEMU → Linux (use Ubuntu 22.04 cloud image or GNS3 built-in)
3. **Connect with links**:
   - FRR `eth0` ↔ AP VM `eth0`
   - AP VM `wlan0` ↔ Client VM `wlan0` (WiFi bridge — see Section 8)
   - FRR `eth1` ↔ Monitor VM `eth0`
4. **Start all nodes** (green play button)
5. **Console into each node** and configure static IPs (see sections 7–10)

### Minimum Topology (8 GB RAM)

If RAM is limited, run only:
- 1 FRR Router (Docker)
- 1 AP VM
- 1 Client VM

Skip Monitor VM and run tcpdump directly on the AP or Client.

---

## 7. FRR Router Configuration

Console into the FRR Docker container or SSH to `192.168.122.10`:

```bash
# Enter FRR shell
vtysh

# Configure interface
configure terminal
interface eth0
 ip address 192.168.122.10/24
exit

# Enable SSH (if using Linux-based FRR image)
exit
```

### DHCP Server (using dnsmasq on FRR or router)

```bash
# On FRR/Linux router
sudo apt install -y dnsmasq
sudo tee /etc/dnsmasq.d/lan.conf <<EOF
interface=eth0
dhcp-range=192.168.122.100,192.168.122.200,255.255.255.0,12h
dhcp-option=3,192.168.122.10
dhcp-option=6,8.8.8.8
EOF
sudo systemctl restart dnsmasq
```

### DNS Forwarding

```bash
# Ensure /etc/resolv.conf points to upstream DNS
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
```

### Enable SSH

```bash
sudo apt install -y openssh-server
sudo systemctl enable ssh
sudo systemctl start ssh

# Set credentials to match configs/devices.yaml
sudo useradd -m admin 2>/dev/null || true
echo "admin:admin" | sudo chpasswd
```

### iperf3 Server

```bash
sudo apt install -y iperf3
iperf3 -s -D    # Run as daemon
```

---

## 8. hostapd Access Point Setup

SSH or console into AP VM (`192.168.122.20`):

```bash
# Set static IP on ethernet (to router)
sudo ip addr add 192.168.122.20/24 dev eth0
sudo ip link set eth0 up
sudo ip route add default via 192.168.122.10

# Install hostapd
sudo apt install -y hostapd bridge-utils

# Create hostapd config
sudo tee /etc/hostapd/hostapd.conf <<EOF
interface=wlan0
driver=nl80211
ssid=TestNet_5G
hw_mode=g
channel=6
wpa=2
wpa_passphrase=Test@12345
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP CCMP
rsn_pairwise=CCMP
EOF

# Enable WiFi interface
sudo ip link set wlan0 up
sudo hostapd /etc/hostapd/hostapd.conf -B

# Enable SSH
sudo apt install -y openssh-server
sudo useradd -m admin 2>/dev/null || true
echo "admin:admin" | sudo chpasswd
sudo systemctl start ssh
```

> **Note:** If `wlan0` does not exist in a VM, use a bridge between `eth1` and a virtual wlan interface, or connect Client VM via ethernet bridge to simulate WiFi L2 connectivity.

---

## 9. Client VM Setup

SSH or console into Client VM (`192.168.122.30`):

```bash
# Install tools
sudo apt install -y wpasupplicant iw iperf3 net-tools openssh-server dnsutils

# Configure wpa_supplicant
sudo tee /etc/wpa_supplicant/wpa_supplicant.conf <<EOF
network={
    ssid="TestNet_5G"
    psk="Test@12345"
    key_mgmt=WPA-PSK
}
EOF

# Connect to AP
sudo wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant.conf
sudo dhclient wlan0

# Or if using ethernet bridge (no real WiFi):
sudo dhclient eth0

# Verify IP
ip addr show

# Enable SSH
sudo useradd -m admin 2>/dev/null || true
echo "admin:admin" | sudo chpasswd
sudo systemctl start ssh
```

---

## 10. Monitor VM Setup

SSH or console into Monitor VM (`192.168.122.40`):

```bash
sudo ip addr add 192.168.122.40/24 dev eth0
sudo ip link set eth0 up
sudo ip route add default via 192.168.122.10

sudo apt install -y tcpdump wireshark openssh-server
sudo useradd -m admin 2>/dev/null || true
echo "admin:admin" | sudo chpasswd
sudo systemctl start ssh

# Test capture
sudo tcpdump -i eth0 -c 5
```

---

## 11. Connectivity Verification

Run this checklist from your **Ubuntu host** (not inside GNS3 nodes):

```bash
# Ping all nodes
ping -c 3 192.168.122.10   # Router
ping -c 3 192.168.122.20   # AP
ping -c 3 192.168.122.30   # Client
ping -c 3 192.168.122.40   # Monitor

# SSH to each node
ssh admin@192.168.122.10   # password: admin
ssh admin@192.168.122.20
ssh admin@192.168.122.30
ssh admin@192.168.122.40

# From client VM — verify DHCP IP
ssh admin@192.168.122.30 "ip addr show"
# Should show 192.168.122.x

# DNS test from client
ssh admin@192.168.122.30 "nslookup google.com"

# iperf3 throughput test
ssh admin@192.168.122.30 "iperf3 -c 192.168.122.10 -t 5"

# SSID scan from client
ssh admin@192.168.122.30 "sudo iwlist wlan0 scan | grep TestNet"
```

All checks must pass before proceeding.

---

## 12. Clone Repo & Python Environment

On your Ubuntu VM:

```bash
# Clone the repository
git clone https://github.com/Nirmal-Yash/wifi-validation-framework.git
cd wifi-validation-framework

# Create virtual environment
python3 -m venv wifi-venv
source wifi-venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create results directories
mkdir -p results/reports results/captures

# Verify imports
python3 -c "import netmiko, pytest, flask, pyshark; print('All imports OK')"
```

---

## 13. Update Configuration Files

Edit `configs/devices.yaml` with your actual lab IPs if they differ:

```yaml
devices:
  router1:
    host: "192.168.122.10"    # ← your FRR router IP
    username: "admin"
    password: "admin"
    device_type: "linux"
    port: 22
  # ... update all nodes
```

Edit `configs/test_params.yaml` if your SSID/password differ:

```yaml
wifi:
  ssid: "TestNet_5G"          # ← must match hostapd.conf
  password: "Test@12345"
```

---

## 14. First Test Run

```bash
cd wifi-validation-framework
source wifi-venv/bin/activate

# Run single DHCP test first
pytest tests/test_dhcp.py -v

# Run all smoke tests
pytest -m smoke -v

# Run full suite with HTML report
pytest tests/ -v --html=results/reports/report.html --self-contained-html

# Save baseline
python regression/baseline_runner.py --version v1.0

# Start dashboard
python dashboard/app.py
# Open http://localhost:5000 in browser
```

### Full Regression Demo

```bash
# 1. Baseline on v1.0
pytest tests/ -v --firmware-version=v1.0
python regression/baseline_runner.py --version v1.0

# 2. Simulate firmware bug
python regression/fw_simulator.py --version v2.0 --bug dns

# 3. Re-test on v2.0
pytest tests/ -v --firmware-version=v2.0

# 4. Generate diff report
python regression/diff_engine.py --version v1.0
# Open results/reports/diff_report.html
```

---

## 15. Troubleshooting

| Problem | Solution |
|---|---|
| GNS3 nodes won't start | Check RAM allocation; reduce to 3-node topology |
| SSH connection refused | `sudo systemctl start ssh` on target VM; check IP |
| `wlan0` not found in VM | Use ethernet bridge between AP and Client VMs |
| PyShark error | `sudo apt install tshark`; `sudo usermod -aG wireshark $USER` |
| iperf3 connection refused | Start server: `iperf3 -s -D` on router |
| DHCP not assigning IP | Check dnsmasq on router; restart: `sudo systemctl restart dnsmasq` |
| hostapd fails to start | Check `wlan0` exists; try `driver=nl80211` or wired bridge |
| Tests fail with timeout | Increase thresholds in `configs/test_params.yaml` |
| Docker permission denied | `sudo usermod -aG docker $USER` and re-login |

---

## Quick Reference — All Install Commands

```bash
# One-shot system setup (run once on fresh Ubuntu 22.04)
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git \
    wireshark tshark iperf3 tcpdump hping3 openssh-server \
    build-essential bridge-utils iw wpasupplicant hostapd dnsmasq
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
sudo usermod -aG wireshark $USER

# Clone and setup project
git clone https://github.com/Nirmal-Yash/wifi-validation-framework.git
cd wifi-validation-framework
python3 -m venv wifi-venv && source wifi-venv/bin/activate
pip install -r requirements.txt
mkdir -p results/reports results/captures

# Run
pytest tests/ -v --html=results/reports/report.html
python dashboard/app.py
```

---

*After completing this guide, refer to [README.md](../README.md) for daily usage and regression workflow.*
