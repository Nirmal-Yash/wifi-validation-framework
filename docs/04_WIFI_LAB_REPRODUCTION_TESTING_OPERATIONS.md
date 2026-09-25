# NetRegress — WiFi Lab Reproduction, Testing & Operations

> Canonical operator document for environment installation, exact GNS3/mac80211_hwsim reproduction, test execution, operational verification, troubleshooting, and recovery.
>
> The original Installation Guide, WiFi Lab Reproduction Guide, and Testing & Operations material are preserved and organized into one operator-facing lifecycle.

## 1. Operator lifecycle

install
→ reproduce exact lab
→ validate connectivity
→ provision
→ run targeted test
→ run full suite
→ inspect evidence
→ diagnose / recover
→ certify

## 2. Installation and environment setup

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

## Iterations 26–27 operational controls
The source installation now includes the certification/security helper CLIs:
- python scripts/netregress_security_audit.py --strict
- python scripts/netregress_certification.py --output results/certification-matrix.json

The canonical development workflow remains on main. Runtime lab execution and protected certification evidence are executed through the dedicated debugging/certification workflow rather than treated as source-install steps.

## 3. Exact WiFi lab reproduction

This document describes the **actual** lab used by `wifi_lab_reprovision_robust.sh` and the pytest suite.

## GNS3 project

| Item | Value |
|------|--------|
| Project name | `WiFi-Regression-Lab` |
| API | `http://127.0.0.1:3080` |

### Nodes (exact names)

| Node | Image | Adapters | Role |
|------|--------|----------|------|
| `frr-router` | `frrouting/frr:latest` | eth0 (unused), **eth1** lab | Router, dnsmasq DHCP, iperf3 server |
| `hostapd-ap` | `gns3/ubuntu:resolute` | **eth0** lab, wlan0 hwsim | AP (hostapd + br0) |
| `wifi-client` | `gns3/ubuntu:resolute` | **eth0** lab side, **eth1** management, wlan0 hwsim | wpa_supplicant client |
| `monitor` | `gns3/ubuntu:resolute` | **eth0** lab | tcpdump |
| `Switch1` / `Cloud` | GNS3 built-in | — | **wifi-client eth1** → `virbr0` for SSH |

### Cabling (manual prerequisite in GNS3 GUI)

1. `frr-router` eth1 ↔ `hostapd-ap` eth0  
2. `frr-router` eth1 ↔ `monitor` eth0 (same L2 segment as AP)  
3. `wifi-client` eth0 ↔ AP segment (L2; WiFi data path uses **hwsim**, not a GNS3 WiFi link)  
4. **`wifi-client` eth1 ↔ Switch or Cloud ↔ host `virbr0`** (management SSH only)  
5. Do **not** use `virbr1` or ad-hoc Docker bridge networks for node interfaces.

## Host prerequisites

- Ubuntu 22.04+ with Docker, libvirt (`default` network), `virbr0` gateway **192.168.122.1**
- Host address on `virbr0`: **10.10.10.1/24** (management gateway for client eth1)
- Kernel module: `mac80211_hwsim` with **2 radios** — **phy0 → AP**, **phy1 → client**
- User in `docker` and `libvirt` groups (or passwordless sudo for host network ops)

## IP / interface roles

| Device | Interface | Address | Purpose |
|--------|-----------|---------|---------|
| FRR | eth1 | 192.168.122.10/24 | Lab router, DHCP, iperf3 |
| AP | br0 (eth0) | 192.168.122.20/24 | Ethernet lab |
| AP | wlan0 | — | SSID `TestNet_5G`, WPA2-PSK `Test@12345`, ch 6 |
| Client | wlan0 | 192.168.122.30/24 (DHCP reservation) | WiFi data tests |
| Client | eth1 | 10.10.10.30/24 | **SSH / Netmiko** (never fault-injected) |
| Client | eth0 | no IPv4 after setup | Lab L2 only |
| Monitor | eth0 | 192.168.122.40/24 | Packet capture |

## WiFi credentials

- SSID: `TestNet_5G`
- WPA2-PSK: `Test@12345`
- Channel: `6`

## DHCP

- **Server:** dnsmasq on FRR `eth1` (installed by reprovision script)
- **Reservation:** client `wlan0` MAC → `192.168.122.30` (discovered at provision time)
- **Management:** client `eth1` uses static `10.10.10.30` (not WiFi DHCP)

## SSH credentials (lab)

- User: `admin` / Password: `admin` on all nodes  
- Pytest connects to **client via `10.10.10.30`** (`configs/devices.yaml` → `client_vm.host`)

## Commands

```bash
cd ~/Desktop/wifi-validation-framework   # or your clone path
chmod +x wifi_lab_reprovision_robust.sh scripts/audit_gns3_lab.sh

# Optional audit
./scripts/audit_gns3_lab.sh

# Provision + validate only
./wifi_lab_reprovision_robust.sh --setup-only

# Full provision + pytest
./wifi_lab_reprovision_robust.sh

# Reproducibility test (stop nodes, reset hwsim, reprovision, pytest)
./wifi_lab_reprovision_robust.sh --repro-test

# Rewrite configs if intentionally changed
./wifi_lab_reprovision_robust.sh --force-normalize-config --setup-only
```

## Validation checklist (script runs these before pytest)

- libvirt `default` active on `virbr0`
- GNS3 nodes started with carrier on required interfaces
- phy0/phy1 in AP/client namespaces, hostapd + wpa_supplicant associated
- FRR dnsmasq + iperf3 listening
- Client default route via `wlan0` and `192.168.122.1`
- SSH + sudo on `10.10.10.30` and monitor
- DNS from client WiFi path

## Ephemeral / runtime state

- GNS3 node run/stop, Docker container PIDs  
- `mac80211_hwsim` module and PHY netns placement  
- hostapd / wpa_supplicant / dnsmasq processes  
- libvirt DHCP host reservations (updated idempotently)  
- `results/` logs, pcaps, SQLite DB (gitignored)

## Recovery

Re-run `./wifi_lab_reprovision_robust.sh` from a normal user shell (not `sudo`). The script is idempotent: active `default` network is OK, missing packages are installed, PHYs are moved only when needed.

If GNS3 topology is missing nodes or client eth1 is not linked to Cloud/Switch, the script **exits with an explicit error** — fix cabling in GNS3, then rerun.

## 4. Testing and operations

## 1. Purpose

This document defines the verification strategy for both the validation product and the framework refactor itself.

The framework must prove real system behavior, while the refactor must prove it did not silently weaken that validation.

## 2. Protected real-lab gate

The current GNS3/mac80211_hwsim suite remains mandatory for any change affecting execution, networking, provisioning, capture, adapters or orchestration.

The current repository has two relevant test scopes.

**Full verification suite** (hardware-free contracts plus protected real-lab tests):

~~~bash
pytest tests/ -v --firmware-version=v1.0
~~~

**Protected GNS3/mac80211_hwsim suite only:**

~~~bash
pytest -m real_lab tests/ -v --firmware-version=v1.0
~~~

To inspect the current protected-suite collection count without executing:

~~~bash
pytest -m real_lab tests/ --collect-only -q
~~~

The documented **11/11 PASS** result belongs specifically to the historical protected baseline commit `436026eba597b2c6ae2e291a9cd8054b70ebbf7c`; it is not the expected collection count of the expanded current repository suite.

## 3. Test layers

### Layer 1 — Unit

Pure business/domain logic.

Examples:

- Run lifecycle;
- classifier;
- sample aggregation;
- threshold calculation;
- configuration resolution;
- artifact hashing;
- capability matching.

### Layer 2 — Component

Service boundaries with fake dependencies.

Examples:

- RunService;
- LabHealthService;
- ArtifactService;
- CommandRunner;
- TestRegistry.

### Layer 3 — Adapter integration

Fake and local Linux adapters exercise orchestration without real hardware.

### Layer 4 — API contract

Validate request/response schemas and error contracts.

### Layer 5 — Migration

Load a copy of the historical SQLite database and verify migrated data and baselines.

### Layer 6 — Real lab

Real GNS3/mac80211_hwsim validation remains the acceptance gate for actual network behavior.

## 4. Current test inventory

Keep the existing tests and node IDs unchanged during Phase 1:

- WPA2 authentication;
- DHCP lease assignment;
- DHCP timing;
- DNS resolution;
- WiFi fault and recovery;
- real DHCP packet capture;
- ping reachability;
- packet loss;
- latency;
- SSID state;
- throughput.

## 5. Evidence requirements

Every test definition declares required evidence.

Examples:

| Test | Required evidence |
|---|---|
| WPA authentication | EAPOL evidence or explicitly defined state evidence |
| DHCP | correlated DORA evidence |
| DNS | query/response correlation |
| throughput | raw samples + aggregate metrics |
| fault recovery | fault action + disruption + recovery |

Required evidence failure produces UNVALIDATED, not PASS.

## 6. Statistical validation

Performance tests use:

- configurable sample count;
- warm-up iterations;
- raw sample persistence;
- median/p95 and other aggregates;
- explicit authoritative metric;
- retained outliers.

Do not silently discard samples or silently replace one failure with a successful retry.

## 6A. Statistical policy verification

Unit tests must verify:

- all configured initial aggregates;
- deterministic percentile interpolation;
- warm-up exclusion;
- exclusion of disallowed sample statuses;
- retry metadata does not duplicate observations;
- minimum sample enforcement;
- metric name/unit compatibility;
- explicit performance-test decision metrics.

The raw `Sample` collection must remain unchanged by aggregate evaluation.

## 7. Failure taxonomy tests

Explicitly inject and verify:

- GNS3 unavailable;
- hwsim unavailable;
- AP unreachable;
- client unreachable;
- router unavailable;
- SSH timeout;
- DHCP failure;
- DNS failure;
- capture failure;
- artifact copy failure;
- database unavailable;
- worker crash;
- Runner disconnect;
- command timeout;
- malformed firmware;
- incompatible firmware;
- reboot failure.

The expected classification must distinguish infrastructure failure from product failure.

## 8. Lab Health verification

Every Run records before/after Lab Health.

Health components must be independently testable.

Health checks are expected to verify both the check logic and the diagnostic artifact generated when a component fails. The component set includes GNS3/project nodes, Docker, libvirt, namespace-scoped hwsim PHYs, management SSH, AP/client/router/monitor interfaces, DHCP, DNS, iperf3, disk and clock/NTP. A required FAILED health result must block test execution and produce LAB_FAILED; DEGRADED/UNKNOWN must remain visible without triggering automatic repair.

## 9. CommandRunner verification

Test:

- structured command result parsing;
- exit code handling;
- stdout/stderr capture;
- timeout handling;
- idempotent retry;
- no retry for mutation;
- sudo handling;
- redaction;
- allow-list enforcement.

## 10. Command security acceptance

Security component tests must prove shell injection rejection, executable allow-list enforcement, destructive-command authorization, centralized sudo -n normalization, secret redaction in command/output/error material, COMMAND_EXECUTED audit events and Run-scoped COMMAND_OUTPUT artifact registration. Real-lab verification remains mandatory because standard pytest command routing changed.
## 11. Artifact verification

Test:

- registration;
- SHA-256;
- file existence;
- corrupted artifact detection;
- missing artifact detection;
- orphan reconciliation;
- authorization on download;
- soft deletion and audit trail.

## 12. Database migration verification

Use the actual current SQLite schema/data as a migration fixture.

Verify:

- all historical test results preserved;
- firmware labels preserved;
- metrics preserved;
- baseline history recoverable;
- imported records clearly marked;
- new Run IDs created only where justified;
- no invented evidence;
- indexes present;
- post-migration queries return expected results.

## 13. Regression verification

Classifier tests must cover:

- PASS to FAIL;
- FAIL to PASS;
- PASS to PASS degradation;
- PASS to PASS improvement;
- no baseline;
- unvalidated evidence;
- incompatible test version;
- multiple metrics;
- per-test thresholds;
- environment mismatch.

## 14. Flaky-test verification

Generate controlled sequences where outcomes alternate under unchanged conditions.

Verify the framework flags inconsistency without replacing raw history with the eventual PASS.

## 15. API contract verification

Every versioned endpoint must have schema validation for:

- success response;
- validation error;
- authorization failure;
- not found;
- infrastructure failure;
- pagination;
- filtering;
- idempotency.

## 16. Security tests

Verify:

- no credential leakage;
- secret redaction;
- dashboard authentication;
- Project-level authorization;
- artifact ACL;
- command injection resistance;
- path traversal resistance;
- HMAC verification;
- idempotency-key behavior;
- audit event generation.

## 17. Real-lab change gate

Any code change affecting these areas requires the 11-test gate:

- connector;
- fault injection;
- capture;
- traffic;
- WiFi analyzer;
- pytest fixtures;
- reprovisioning;
- device adapters;
- Run orchestration.

If the physical lab is unavailable, state that limitation explicitly. Do not claim the real-lab gate passed.

## 18. Operational run modes

### Full validation
Provision lab, run health, execute full test suite, collect evidence.

### Setup only
Provision and validate environment without running tests.

### Repro-test
Reset runtime WiFi state, reprovision and run the full suite.

### Configuration normalization
Explicitly rewrite configuration only when requested.

Existing shell flags remain supported during migration.

## 19. Operational evidence

Expected runtime directories:

~~~text
results/test_results.db
results/reports/
results/captures/
results/setup-logs/
~~~

Runtime evidence remains gitignored.

## 20. Acceptance gates by phase

### Phase 1
- new Run IDs present;
- existing CLI works;
- legacy DB migration passes;
- 11/11 real-lab suite.

### Phase 1S
- security checks pass;
- credentials removed from tracked config;
- authentication/authorization active.

### Phase 2
- Lab Health distinguishes healthy/degraded/failed;
- diagnostic bundle generated;
- real suite remains green.

### Phase 3
- raw samples and aggregates persisted;
- statistical thresholds work;
- performance suite remains valid.

### Phase 7
- NO_BASELINE and UNVALIDATED are distinct;
- richer classification works;
- incompatible comparisons are blocked.

### Phase 8
- dashboard uses v1 APIs;
- run detail and evidence pages work;
- read-only behavior remains secure.

### Phase 9
- fake adapter integration suite passes;
- physical adapter can identify/flash/verify where available;
- rollback path tested if supported.

## 21. Regression-proof refactor rule

The framework is itself a system under validation.

Every functional refactor must prove:

~~~text
old intended behavior preserved
+
new behavior correctly evidenced
+
no weakened assertion
~~~


## 22. Iteration 12 recovery validation

The expanded functional suite contains explicit disruption/recovery cases for:

- WPA2 wrong-PSK rejection and recovery;
- WiFi disconnect/reconnect;
- DHCP renewal;
- DHCP service interruption and lease recovery;
- DNS failure/recovery;
- AP hostapd restart/recovery;
- client wpa_supplicant restart/recovery.

Each destructive case preserves the management path and must prove both the fault and the restored data/control path. Fault application and restoration are audited through CommandRunner, and FaultService restores state in a finalization boundary.

The original 11 validation tests remain the protected behavioral subset. Because Iteration 12 adds real network-mutating tests, both the protected subset and the expanded recovery suite require execution on the GNS3/mac80211_hwsim lab before this iteration can be considered runtime-verified.

Protocol-accurate DHCP T2 rebind is not inferred from a generic lease reacquisition. That assertion is reserved for the later transaction-aware DHCP evidence phase.

## 23. Iteration 13 protocol evidence validation

Protocol analyzer tests must verify:

- DHCP correlation by transaction ID and client identity;
- DORA ordering rather than independent packet counts;
- EAPOL four-way message ordering;
- beacon RSN/cipher/AKM extraction;
- DNS query/response transaction correlation;
- raw PCAP remains unchanged after analysis;
- derived protocol evidence can be serialized and registered as Run-scoped evidence.

The real DHCP capture test must continue using the protected AP `br0` tcpdump + SFTP + SHA-256 path while its assertion is upgraded from packet count/ACK presence to correlated DORA evidence.

## 24. Iteration 14 telemetry validation

Telemetry unit tests must verify:

- parsing of `wpa_cli signal_poll`, `iw link` and `iw station dump`;
- RSSI/SNR/frequency/channel/bitrate extraction;
- PHY-mode extraction only from observed driver bitrate data;
- retry/failure counters remain explicitly labeled as counters;
- environment class is present on the snapshot and every point;
- invalid interfaces are rejected before command execution;
- completely missing source observations are not converted into fabricated measurements;
- JSON serialization preserves environment class on every point.

The telemetry service uses read-only commands through `SecureCommandRunner`; it does not alter the protected DHCP capture or validation traffic paths.


## 25. Iteration 15 regression-intelligence validation

Targeted tests must verify:
- explicit baseline Run identity;
- incompatible environment/profile/lab/test-definition context is blocked;
- missing comparison context is never guessed;
- PASS→FAIL and FAIL→PASS classification;
- multiple metrics use declared statistical decision values;
- per-test/per-metric thresholds override the compatibility default;
- missing current results become `UNVALIDATED`;
- invalid current evidence becomes `UNVALIDATED`;
- baseline-side invalid evidence prevents comparison;
- new tests remain explicitly visible as `NEW_PASS`/`NEW_FAILURE`;
- flaky history is retained without mutating the primary classification.

The legacy firmware-string regression path remains a compatibility boundary and is not treated as the authoritative Phase 7 engine.


## 26. Iteration 16 dashboard/API validation

Targeted verification must cover:
- /api/v1 success and error envelope consistency;
- Run filters and pagination;
- Run/Test detail from persisted Run/Attempt/TestResult state;
- explicit-baseline regression comparison;
- visible incompatible/missing comparison context;
- performance sample history;
- telemetry environment/source/timestamp presentation;
- health snapshot display without repair;
- artifact SHA-256 verification before JSON interpretation;
- artifact download containment under results/;
- legacy /api/* compatibility routes.


## 27. Iteration 17 adapter validation

Adapter tests cover capability declarations, Linux/OpenWrt profile behavior, version parsing, image hash/model validation, explicit authorization, nominal lifecycle, flash failure, reboot failure without implicit rollback and explicit rollback.

Operational acceptance still requires real-hardware flash/reboot/rollback tests against the supported device family before production firmware control is enabled. Those physical operations were not executed in this environment.

## 28. Iteration 18 CI gate

The always-on GitHub-hosted job is hardware-free and runs ci_tests outside the real-lab pytest conftest. The protected lab job is explicitly dispatchable on a self-hosted netregress-lab runner. The persisted release evaluator rejects missing or invalid release evidence instead of treating unavailable infrastructure as a product PASS.

## 29. Iteration 19 offline operation

At Run completion, the pytest session attempts to enqueue a local snapshot. Queue failure emits a warning and does not change the Run outcome.

Synchronization is explicit through `python scripts/netregress_sync.py --url https://...`. Temporary connectivity failures remain retryable. Stale in-flight leases are recoverable. Repeated delivery uses the same idempotency key so the future Cloud can safely deduplicate accepted envelopes.

The current environment has no configured Cloud endpoint, so no external synchronization was attempted.

## Iterations 23–25 operational implementation
Failure taxonomy, process cancellation, diagnostic bundle generation, reproduction manifests, explicit firmware lifecycle and release/baseline controls are implemented as Runner operational paths. The dedicated Debugging Phase is the validation stage for real execution, lab behavior and fault-injection scenarios; implementation work should not add alternate fake production paths to satisfy that phase.


## 30. Iterations 26–27 verification contracts
Iteration 26 introduces a typed 27-case failure-injection catalog and harness. Hardware-free tests validate Run failure-class persistence, cleanup contracts, idempotency durability, CSRF/SSRF controls, restart recovery, stale-lock recovery, audit-chain integrity and backup/restore.

The integration boundary remains three-layered:
1. hardware-free domain/service/repository/API/security tests;
2. simulated integration through deterministic fake adapters and controlled failures;
3. protected real-lab execution through the existing GNS3/mac80211_hwsim topology.

Iteration 27 introduces the final 11-scenario certification matrix. A scenario is evidence-complete only when every required control is present. Source-only CI generates the matrix and validates its contract but does not substitute synthetic evidence for the protected real-lab baseline.

## Iterations 28–30 release verification
Iteration 28 validates release structure through source compilation, security/readiness checks, certification-matrix generation, working-tree auditing and the release manifest. Iteration 29 adds reproducible RunnerDoctor checks plus SQLite integrity inspection and content-addressed release inventory. Iteration 30 freezes the architecture/security/testing contract while preserving the distinction between source readiness and protected real-lab certification evidence.

~~~bash
python scripts/netregress_release.py verify
python scripts/netregress_release.py doctor
python scripts/netregress_release.py manifest
~~~

## 5. Operational boundary

- Reprovisioning is an explicit operator-invoked repair/retry action.
- Degraded or unverified lab state must never be presented as validated evidence.
- Management connectivity remains separate from the WiFi test path.
- Raw PCAP and integrity hashes remain authoritative.
- Runtime artifacts stay outside tracked source.
- Protected REAL_LAB execution remains authoritative for execution-sensitive behavior.
