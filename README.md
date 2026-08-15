# NetForge — Wi-Fi & Network Validation Framework

NetForge is a Linux-first network validation framework combining Pytest, SQLite result storage, network namespaces, `mac80211_hwsim`, optional GNS3 integration, packet evidence, regression analysis, and a Flask control-plane dashboard.

> **Engineering status:** the repository is designed for reproducible validation. The dashboard/database layer is deterministic without privileged networking. Tier-1 live Wi-Fi behavior must be proven on the target Linux lab host; this repository cannot honestly claim physical hwsim behavior from source inspection alone.

## Repository contract

```text
wifi-validation-framework/
├── config/                 # Runtime topology/device configuration
├── db/                     # Canonical SQLite schema and bootstrap
├── dashboard/              # Flask control plane and topology UI
├── engine/                 # Import/regression/execution building blocks
├── scripts/                # Provisioning, teardown and verification
├── tests/                  # Deterministic + privileged live tests
├── artifacts/              # Runtime evidence/uploads; do not commit secrets
└── docs/EXACT_SETUP_AND_EXECUTION.md
```

## Key engineering guarantees

- Canonical, idempotent SQLite schema/bootstrap.
- Versioned topology state with `DRAFT → ACTIVE → ARCHIVED` lifecycle.
- Structured dashboard/API errors and health checks.
- GNS3 synchronization is optional and isolated from the local topology lifecycle.
- Privileged tests are explicitly marked `live`.
- Tier-1 provisioning starts from a clean `mac80211_hwsim` state instead of trusting stale radios.
- PHY/interface role mapping is preserved even when Linux assigns different host WLAN names.
- Namespace teardown kills namespace-owned processes before removing namespaces.
- Provisioning retries transient PHY `EBUSY` conditions and emits diagnostics when ownership remains.
- Enterprise PEAP test certificates are generated ephemerally at setup time instead of committing private keys.
- Physical/Tier-2 credentials are kept outside source-controlled topology configuration.

## Quick start

### 1. Linux dependencies

Ubuntu 22.04/24.04 is recommended.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3 iproute2 iw tcpdump tshark hostapd wpasupplicant dnsmasq isc-dhcp-client iperf3 openssl
```

If your kernel separates wireless modules:

```bash
sudo apt install -y linux-modules-extra-$(uname -r) || true
sudo depmod -a
```

### 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
```

### 3. Verify the application layer

```bash
python scripts/verify_installation.py
python db/init_db.py
pytest -q -m 'not live'
```

### 4. Start the dashboard

```bash
python -m dashboard.app
```

Open `http://127.0.0.1:5000/`.

Health:

```bash
curl -fsS http://127.0.0.1:5000/health
```

Topology API:

```bash
curl -fsS http://127.0.0.1:5000/api/topology_data
```

## Tier-1 live Wi-Fi lab

Use a disposable/isolated Linux lab host. The setup script deliberately resets stale virtual radios before creating the lab, so **do not manually create `wlan0`, `wlan1`, or `wlan2` first**.

```bash
sudo chmod +x scripts/*.sh
sudo ./scripts/teardown_topology.sh
sudo ./scripts/setup_topology.sh
```

Successful setup ends with:

```text
NetForge Tier-1 topology ready
  AP: ap_ns/wlan0
  Client: client_ns/wlan1
  Monitor: monitor_ns/wlan2
  AP: 192.168.50.1/24
```

The script:

1. stops known lab daemons;
2. releases detected hwsim interfaces from NetworkManager;
3. removes stale NetForge namespaces and their processes;
4. unloads any existing `mac80211_hwsim` instance;
5. loads exactly three fresh hwsim radios;
6. preserves the discovered PHY/interface mapping;
7. moves each PHY into its dedicated namespace;
8. renames the interfaces to the canonical NetForge names;
9. configures channel 6 and monitor mode while interfaces are down;
10. creates ephemeral enterprise CA/server credentials for PEAP testing;
11. verifies the final namespaces, interfaces and AP address.

Run the live suite only after setup succeeds:

```bash
NETFORGE_LIVE_TESTS=1 python -m pytest -q tests/ -v -m live --fw-version=1.0.0
```

## `Device or resource busy (-16)`

The setup script is specifically hardened against this failure. If it still occurs, it is evidence that a host-level process/service is retaining the radio, not a condition that should be hidden by endless retries.

Run:

```bash
sudo ./scripts/teardown_topology.sh
sudo ./scripts/setup_topology.sh
```

If setup fails, capture the diagnostic output and inspect:

```bash
sudo ip netns list
sudo iw dev
lsmod | grep mac80211_hwsim || true
sudo fuser -v /sys/class/ieee80211/phy* 2>&1 || true
systemctl list-units --all 'wpa_supplicant*'
nmcli device status 2>/dev/null || true
```

Do not disable NetworkManager globally on a normal workstation merely to make the test pass. The intended target is an isolated lab host.

## GNS3

The topology workspace can load a GNS3 project as a preview. The active database topology is not replaced until the preview is deliberately adopted through a draft and committed.

Default server:

```text
http://localhost:3080
```

Project UUID is required. If GNS3 is unavailable, the rest of the dashboard must remain functional.

## Evidence

Runtime evidence is stored under:

```text
db/results.db
artifacts/pcaps/
artifacts/uploads/
config/certs/        # ephemeral live-test TLS material
```

Generated evidence and private keys must not be committed.

## Tier-2 physical hardware

Never put physical credentials into `config/devices.yaml`. Use environment variables or an approved secret manager:

```bash
export NETFORGE_CISCO_USERNAME='...'
export NETFORGE_CISCO_PASSWORD='...'
export NETFORGE_CISCO_SECRET='...'
```

## Authoritative documentation

For the exact installation, provisioning, validation and troubleshooting sequence, use:

`docs/EXACT_SETUP_AND_EXECUTION.md`

## Definition of done

A NetForge installation is considered operational only after both gates pass:

### Gate A — deterministic software gate

```bash
python scripts/verify_installation.py
pytest -q -m 'not live'
```

### Gate B — target Linux live gate

```bash
sudo ./scripts/teardown_topology.sh
sudo ./scripts/setup_topology.sh
NETFORGE_LIVE_TESTS=1 python -m pytest -q tests/ -v -m live --fw-version=1.0.0
```

The source code can make Gate B reproducible and diagnostic, but only execution on the target Linux lab can prove that gate. That distinction is intentional SDET practice, not a limitation hidden from the user.
