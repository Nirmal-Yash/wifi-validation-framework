# NetForge — Exact Setup & Execution Guide

This guide is the authoritative setup procedure for the `fix/stable-baseline` branch. Follow it in order. Do not reuse commands from older README revisions.

## 1. Supported baseline

Recommended: Ubuntu 22.04/24.04 on a real Linux host or VM with permission to use network namespaces. Tier-1 live Wi-Fi tests require a kernel with `mac80211_hwsim` and tools such as `ip`, `iw`, `hostapd`, `wpa_supplicant`, `wpa_cli`, `dnsmasq`, `tcpdump`, `dhclient`, `ethtool` and `openssl`.

The dashboard/database verifier does **not** require privileged networking.

## 2. Clone and enter the repository

```bash
git clone https://github.com/Nirmal-Yash/wifi-validation-framework.git
cd wifi-validation-framework
git checkout fix/stable-baseline
```

Confirm the branch:

```bash
git branch --show-current
git log -1 --oneline
```

## 3. Install OS packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3 iproute2 iw tcpdump tshark hostapd wpasupplicant dnsmasq isc-dhcp-client iperf3 openssl
```

For kernels that split wireless extras:

```bash
sudo apt install -y linux-modules-extra-$(uname -r) || true
sudo depmod -a
```

## 4. Create the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
```

## 5. Verify the repository before running anything privileged

```bash
python scripts/verify_installation.py
```

Expected final line:

```text
NETFORGE INSTALLATION VERIFICATION: PASS
```

If this fails, do not proceed to live topology setup. Fix the reported dependency, database, import, or topology issue first.

## 6. Initialize the database

```bash
python db/init_db.py
```

This creates `db/results.db` and applies `db/schema.sql`. The bootstrap is idempotent; running it again is safe.

To validate only:

```bash
python -c "from db.init_db import validate; print(validate())"
```

## 7. Start the dashboard

Preferred module execution:

```bash
python -m dashboard.app
```

Open:

```text
http://127.0.0.1:5000/
```

Health check:

```bash
curl -fsS http://127.0.0.1:5000/health
```

The response must contain `"database":"ok"`.

Topology API:

```bash
curl -fsS http://127.0.0.1:5000/api/topology_data
```

The response must contain `"success":true`.

## 8. Topology page

Navigate to `/topology`.

The page reads the canonical topology model from SQLite. On a new database, the current `config/devices.yaml` is imported once as the initial topology seed.

The topology editor can:

- display nodes;
- move nodes;
- add local canvas nodes;
- edit device configuration;
- validate node/link references;
- commit a topology version;
- import supported `.json`/`.gns3` files when the importer is available;
- synchronize with a running GNS3 server when `gns3fy` is installed.

## 9. GNS3 synchronization

Start GNS3 Server and obtain the project UUID. In the topology page enter:

```text
Server: http://localhost:3080
Project UUID: <UUID>
```

Then use the GNS3 import/preview workflow. A preview never replaces the active topology until you explicitly adopt it through a draft and commit it.

CLI diagnostic:

```bash
curl -sS -X POST http://127.0.0.1:5000/api/topology/gns3 \
  -H 'Content-Type: application/json' \
  -d '{"server_url":"http://localhost:3080","project_id":"YOUR_UUID"}'
```

A GNS3 connection problem is returned as a structured `502` error; it should not appear as an unexplained application 500.

## 10. Run the non-privileged test suite

```bash
pytest -q -m 'not live'
```

The suite is intentionally prevented from modifying the host networking stack unless explicitly enabled.

## 11. Enable live Tier-1 networking

Only do this on a disposable test host or approved lab machine. The provisioning script deliberately resets stale `mac80211_hwsim` state before creating a fresh three-radio lab. This avoids reusing a partially configured radio set and prevents PHY/interface ordering drift.

Provision:

```bash
sudo chmod +x scripts/*.sh
sudo ./scripts/teardown_topology.sh
sudo ./scripts/setup_topology.sh
```

A successful setup ends with:

```text
NetForge Tier-1 topology ready
  AP: ap_ns/wlan0
  Client: client_ns/wlan1
  Monitor: monitor_ns/wlan2
  AP: 192.168.50.1/24
```

Verify namespaces:

```bash
sudo ip netns list
```

Verify hwsim:

```bash
lsmod | grep mac80211_hwsim || true
sudo ip netns exec ap_ns iw dev
sudo ip netns exec client_ns iw dev
sudo ip netns exec monitor_ns iw dev
```

The script generates short-lived enterprise test certificates under `config/certs/`; these are runtime lab credentials and are not intended for Git. The generated private key is protected by the script's `umask 077`.

Run privileged tests only after topology setup succeeds:

```bash
NETFORGE_LIVE_TESTS=1 python -m pytest -q tests/ -v --fw-version=1.0.0 -m live
```

## 12. Evidence and results

Results are stored in:

```text
db/results.db
artifacts/pcaps/
artifacts/uploads/
```

Never commit generated `results.db`, packet captures, runtime TLS keys, credentials, or private lab artifacts unless explicitly intended.

## 13. Tier-2 physical hardware

Tier-2 credentials must not be placed in `config/devices.yaml`.

Set secrets in the shell/session or approved secret manager, for example:

```bash
export NETFORGE_CISCO_USERNAME='...'
export NETFORGE_CISCO_PASSWORD='...'
export NETFORGE_CISCO_SECRET='...'
```

Use a local `.env` only if your deployment policy permits it, and ensure it is ignored by Git.

## 14. Troubleshooting

### `command failed: Device or resource busy (-16)` during setup

This normally means the wireless PHY still has a userspace owner or stale virtual-radio state. The current setup script already performs a deterministic reset, stops known Wi-Fi daemons, releases NetworkManager ownership for detected hwsim interfaces, removes stale namespaces, unloads `mac80211_hwsim`, and creates a fresh three-radio instance.

Run exactly:

```bash
sudo ./scripts/teardown_topology.sh
sudo ./scripts/setup_topology.sh
```

If it still fails, **do not repeatedly rerun setup**. The script now prints the failed PHY, ownership information and hwsim inventory. Also run:

```bash
sudo ip netns list
lsmod | grep mac80211_hwsim || true
sudo iw dev
sudo fuser -v /sys/class/ieee80211/phy* 2>&1 || true
systemctl list-units --all 'wpa_supplicant*'
nmcli device status 2>/dev/null || true
```

If `mac80211_hwsim` cannot be unloaded, a host service is still holding it. Stop that service before retrying. Do not disable NetworkManager globally unless this is an isolated lab host.

### Dashboard returns 500

Run:

```bash
curl -v http://127.0.0.1:5000/health
python scripts/verify_installation.py
```

Then inspect the terminal running Flask. API failures are returned with an error code and message.

### Topology page is blank

Run:

```bash
curl -fsS http://127.0.0.1:5000/api/topology_data
python db/init_db.py
```

If `nodes` is empty, inspect `config/devices.yaml` and ensure it contains a `nodes:` mapping.

### GNS3 sync fails

Check:

```bash
curl -fsS http://localhost:3080/v2/version
```

Then verify the project UUID and that the bundled GNS3 compatibility client is available.

### Live tests fail before test logic

Do not repeatedly rerun with sudo. Check:

```bash
sudo ip netns list
lsmod | grep mac80211_hwsim
which ip iw hostapd wpa_supplicant wpa_cli dnsmasq tcpdump dhclient openssl
```

Then inspect the provisioning script and its command output.

### Enterprise 802.1X fails at TLS setup

The live setup generates a temporary CA and server certificate. Confirm:

```bash
ls -l config/certs/
sudo ip netns exec ap_ns hostapd -t config/hostapd_enterprise.conf
```

If the certificate files are missing, rerun the complete teardown/setup sequence.

### Database is corrupt or stale

For a disposable development database:

```bash
rm -f db/results.db db/results.db-shm db/results.db-wal
python db/init_db.py
```

Do not delete a database containing evidence you need to preserve.

## 15. Security requirements

- Never commit real passwords.
- Rotate any credential that was previously committed to Git.
- Do not expose the Flask development server directly to the Internet.
- Run live network tests only on an isolated lab host.
- Treat PCAPs as potentially sensitive artifacts.
- Keep production credentials outside source-controlled YAML/JSON.
- Treat generated `config/certs/*.key` files as secrets even though they are ephemeral test credentials.

## 16. Definition of a healthy installation

A baseline installation is healthy only when all of these are true:

1. `python scripts/verify_installation.py` passes.
2. `python db/init_db.py` passes.
3. `/health` returns HTTP 200.
4. `/api/topology_data` returns HTTP 200 with `success=true`.
5. `/topology` renders without a backend error.
6. `pytest -q -m 'not live'` completes without infrastructure-induced collection failures.
7. `sudo ./scripts/setup_topology.sh` completes with the exact Tier-1 topology-ready message.
8. `NETFORGE_LIVE_TESTS=1 python -m pytest -q tests/ -v -m live` is executed on the target Linux lab and produces real test evidence.

Passing the dashboard verifier alone does not claim that physical hardware, GNS3, hwsim, or RF behavior is available. Those capabilities require the target environment and must be validated by the live gate.
