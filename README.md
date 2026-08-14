# NetForge — Wi-Fi & Network Validation Framework

NetForge is a Linux-first network validation framework combining Pytest, SQLite result storage, network namespaces, `mac80211_hwsim`, optional GNS3 integration, packet evidence, regression analysis, and a Flask control-plane dashboard.

> **Baseline status:** this branch is a stabilization baseline. Dashboard/database functionality can be verified without privileged networking. Tier-1 live tests require a deliberately provisioned Linux networking environment. Tier-2 hardware requires separate lab credentials and connectivity.

## Repository contract

```text
wifi-validation-framework/
├── config/                 # Runtime topology/device configuration
├── db/
│   ├── schema.sql          # Canonical database schema
│   └── init_db.py          # Idempotent database bootstrap/validator
├── dashboard/
│   ├── app.py              # Flask control plane and API
│   ├── db.py               # Shared SQLite connection/bootstrap layer
│   └── templates/          # Dashboard UI
├── engine/                 # Execution/import/regression building blocks
├── scripts/
│   ├── setup_topology.sh   # Privileged Tier-1 provisioning
│   ├── teardown_topology.sh
│   └── verify_installation.py
├── tests/                  # Pytest validation suite
├── artifacts/              # Runtime evidence/uploads; do not commit secrets
└── docs/
    └── EXACT_SETUP_AND_EXECUTION.md
```

## What was fixed in this baseline

- One canonical SQLite schema instead of assuming `results.db` already exists.
- Idempotent database initialization and schema validation.
- Shared dashboard DB connection with foreign-key enforcement.
- Topology persistence model with topology versions, nodes and links.
- Legacy `config/devices.yaml` is used only as an initial seed when the database has no topology.
- `/health` and deterministic topology API verification endpoints.
- Structured API errors instead of unexplained backend failures.
- GNS3 synchronization is explicitly optional and returns a controlled `503/502` when unavailable.
- Topology commit stores nodes and links as a versioned database object.
- Test bootstrap no longer silently ignores a missing database.
- Privileged namespace setup is opt-in through `NETFORGE_LIVE_TESTS=1`.
- Physical credentials were removed from the committed topology configuration.
- Installation verification is executable rather than merely descriptive.

## Quick start

### 1. Linux dependencies

Ubuntu is recommended.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3 iproute2 tcpdump tshark hostapd wpasupplicant dnsmasq isc-dhcp-client iperf3
```

### 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
```

### 3. Verify

```bash
python scripts/verify_installation.py
```

### 4. Initialize database

```bash
python db/init_db.py
```

### 5. Run tests without privileged networking

```bash
pytest -q
```

### 6. Start dashboard

```bash
python -m dashboard.app
```

Open `http://127.0.0.1:5000/`.

Health:

```bash
curl -fsS http://127.0.0.1:5000/health
```

Topology data:

```bash
curl -fsS http://127.0.0.1:5000/api/topology_data
```

## Live Tier-1 testing

Live testing is intentionally separated from ordinary Python tests because it can change the host networking stack.

```bash
sudo chmod +x scripts/*.sh
sudo ./scripts/teardown_topology.sh
sudo ./scripts/setup_topology.sh
sudo ip netns list
```

Only after successful provisioning:

```bash
sudo -E env PATH="$PATH" NETFORGE_LIVE_TESTS=1 pytest -q tests/ -v --fw-version=1.0.0
```

## GNS3

The topology page supports optional live GNS3 synchronization. Default server URL:

```text
http://localhost:3080
```

A valid GNS3 project UUID is required. If GNS3 is not available, the rest of the dashboard must remain usable.

## Database

The canonical schema is in `db/schema.sql`. The database contains firmware/test history plus versioned topology, execution, result, evidence, baseline, regression and audit records.

For a disposable development reset:

```bash
rm -f db/results.db db/results.db-shm db/results.db-wal
python db/init_db.py
```

Do not perform this reset on evidence you need to preserve.

## Security

The repository must never contain real Tier-2 credentials. `config/devices.yaml` uses environment-variable names for physical credentials.

If any password that was previously committed is real, rotate it. Removing a password from the latest file does not remove it from Git history.

## Authoritative setup documentation

Use [`docs/EXACT_SETUP_AND_EXECUTION.md`](docs/EXACT_SETUP_AND_EXECUTION.md) as the command-by-command installation, execution and troubleshooting guide.
