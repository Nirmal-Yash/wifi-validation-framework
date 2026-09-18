# WiFi Lab Reproduction Guide (GNS3 + mac80211_hwsim)

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
