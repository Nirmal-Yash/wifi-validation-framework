Here is the complete, production-ready `README.md` file for your repository. It encapsulates all 20 phases of your architecture, detailing the exact system dependencies, the Tier 1 vs. Tier 2 capabilities, and the strict sequence required to reproduce the environment without errors.

---

# NetForge: Advanced Wi-Fi & Network Validation Framework

NetForge is a production-grade, automated Software Quality Assurance (QA) architecture engineered to execute rigorous network validation testing across complex wireless and routed environments.

By leveraging the Linux kernel's `mac80211_hwsim` driver and Network Namespaces (`netns`), NetForge creates virtual Wi-Fi radios and isolated routing boundaries directly in system memory. This enables high-velocity, deterministic testing of enterprise network protocols—from Wi-Fi 7 Multi-Link Operation (MLO) to 802.1Q VLANs—without requiring expensive physical RF hardware or anechoic chambers.

---

## 🚀 Core Capabilities

* **Zero-Hardware RF Simulation (Tier 1):** Bypasses physical hardware limits using `mac80211_hwsim`, executing raw 802.11 frames natively in the Linux kernel.
* **Next-Gen Protocol Validation:** Automated Pytest assertions for WPA3-SAE handshakes, Wi-Fi 7 MLO hitless failovers, 802.1X Enterprise (EAP-PEAP), and TR-369 USP Remote Telemetry.
* **L2/L3 Routing Infrastructure:** Validates core routing functions including 802.1Q VLAN segregation, DHCP IP allocation, and EtherChannel (LACP) negotiation.
* **Chaos Engineering:** Dynamically injects packet loss and latency using `tc netem` to test TCP stack resilience under degraded physical conditions.
* **Regression Intelligence:** Intercepts silent Pass-to-Fail firmware transitions across simulated dual-bank (A/B) OTA flashes, tracked via SQLite.
* **Glassmorphic NOC Dashboard:** A fully interactive Network Operations Center (NOC) UI built with Flask and Vis.js, featuring real-time GNS3 topology synchronization and strict JSON device configurations.

---

## 🛠️ System Architecture

NetForge bridges the gap between software simulation and physical network engineering using a 7-layer architecture:

```text
wifi-validation-framework/
├── config/
│   ├── devices.yaml         # Spatial coordinates & netns bridging map
│   └── *.json               # Extracted device-specific configurations
├── db/
│   ├── results.db           # SQLite regression metrics engine
│   └── schema.sql           # Database initialization
├── engine/
│   ├── diff_engine.py       # Detects pass-to-fail regressions against baselines
│   ├── fw_simulator.py      # Simulates dual-bank OTA flashing
│   ├── hil_abstractor.py    # Routes SSH commands for Physical Tier 2 execution
│   └── topology_importer.py # Parses .gns3 files via Euclidean mapping
├── dashboard/
│   ├── app.py               # Flask Control Plane, REST API, & GNS3 sync
│   └── templates/           # Void-Amber UI templates
├── scripts/
│   ├── setup_topology.sh    # Provisions hwsim radios and network namespaces
│   └── teardown_topology.sh # Force-kills daemons and unloads kernel modules
└── tests/
    ├── conftest.py          # Pytest setup hooks, daemon configs & PCAP generators
    ├── test_auth.py         # WPA3-SAE association logic
    ├── test_dhcp.py         # IP allocation via Scapy
    ├── test_throughput.py   # Data-plane speed validation
    ├── test_mlo_failover.py # Wi-Fi 7 Multi-Link drop simulations
    ├── test_usp_telemetry.py # TR-369 ISP remote disable validation
    ├── test_attenuation_roaming.py # Client roaming scans
    ├── test_chaos_throughput.py    # tc netem network degradation
    ├── test_l2_l3_infrastructure.py# VLAN and EtherChannel tests
    └── test_8021x_enterprise.py    # WPA-Enterprise RADIUS validation

```

---

## ⚙️ Prerequisites & Dependencies

NetForge requires a Linux environment (Ubuntu 20.04/22.04 recommended) to natively access the kernel's wireless subsystems.

**1. System Dependencies:**

```bash
sudo apt-get update
sudo apt-get install -y isc-dhcp-client sqlite3 tcpdump tshark macchanger bridge-utils vlan hostapd wpasupplicant dnsmasq

```

**2. Kernel Wireless Extras:**
If running on a cloud VM (like Azure) or a stripped kernel, you must inject the wireless modules:

```bash
sudo apt-get install -y linux-modules-extra-$(uname -r)
sudo depmod -a

```

**3. Python Virtual Environment:**

```bash
python3 -m venv wifi-venv
source wifi-venv/bin/activate
pip install pytest flask scapy gns3fy pyyaml netmiko

```

---

## 🏁 Execution & Reproduction Steps

Follow this strict sequence to clear the host kernel, provision the virtual airwaves, and execute the automated regression suite.

### Step 1: Database Initialization

Initialize the SQLite engine to track firmware performance.

```bash
rm -f db/results.db
sqlite3 db/results.db < db/schema.sql

```

### Step 2: Environment Teardown & Provisioning

Ensure no zombie daemons (`hostapd`, `dnsmasq`) or stale kernel modules are holding system locks, then instantiate the virtual radios.

```bash
sudo chmod +x scripts/teardown_topology.sh scripts/setup_topology.sh
sudo ./scripts/teardown_topology.sh
sudo ./scripts/setup_topology.sh

```

### Step 3: Trigger the Regression Suite

Execute the baseline firmware validation (v1.0.0). The master `conftest.py` fixture will autonomously isolate each test into a clean namespace, start the daemons, execute the assertions, and safely generate AppArmor-compliant `.pcap` artifacts.

```bash
sudo -E env "PATH=$PATH" python3 -m pytest tests/ -v --fw-version=1.0.0

```

*To test regression intelligence, trigger a candidate upgrade (e.g., `--fw-version=1.0.1`) and observe the Pass/Fail deltas.*

### Step 4: Launch the NOC Dashboard

Boot the Flask control plane to visualize the execution metrics and manage the live network topology.

```bash
python3 dashboard/app.py

```

*Access the UI at `[http://127.0.0.1:5000](http://127.0.0.1:5000)`.*

---

## 📡 GNS3 Live Synchronization

NetForge features direct API interoperability with GNS3 to overlay testing metrics onto physical topology coordinates.

1. Ensure the GNS3 Server is running (default `http://localhost:3080`).
2. Navigate to the **Topology Work** tab in the NetForge Dashboard.
3. Enter your GNS3 **Project UUID** and click **Sync GNS3**.
4. The backend will parse the `.gns3` layout, map the nodes to the canvas, and dynamically highlight components in **Red** if the SQLite database detects recent critical failures (e.g., DHCP or Auth module drops) associated with that device.

---

## 🔧 Tier 1 vs. Tier 2 Testing Modes

NetForge is designed to seamlessly abstract execution between simulated and physical environments.

* **Tier 1 (Virtual SoftMAC):** The default configuration. All `sudo ip netns exec` commands route strictly to isolated Linux RAM namespaces.
* **Tier 2 (Hardware-in-the-Loop):** By updating `config/devices.yaml` to `environment_type: "tier2_physical"`, the `hil_abstractor.py` engine reroutes all test assertions out of the local kernel, tunneling them via SSH (Netmiko) directly into physical lab hardware (e.g., Cisco ISR routers, Catalyst Switches, or programmable RF attenuators).
