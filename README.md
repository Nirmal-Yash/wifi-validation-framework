# WiFi Validation Framework

Automated regression testing framework for WiFi and network devices. Runs a full suite of feature tests — DHCP, SSID visibility, WPA2 authentication, DNS, throughput, ping latency, and packet capture — and when a firmware update happens, automatically re-runs those tests and generates a diff report showing exactly what changed in behavior.

Built with **Pytest**, **Netmiko**, **GNS3**, **SQLite**, and **Flask** — mirroring industry-standard network QA practices.

## Architecture

```
Layer 1  Virtual Lab (GNS3 + FRR + hostapd + Linux VMs)
Layer 2  Config Manager (YAML + Jinja2 templates)
Layer 3  Device Connectivity (Netmiko SSH pool)
Layer 4  Traffic & Validation (iperf3, tcpdump, PyShark)
Layer 5  Test Engine (Pytest — 8 test files)
Layer 6  Regression Engine (baseline, diff, fw_simulator)
Layer 7  Dashboard & Reporting (Flask + SQLite + HTML reports)
```

## Quick Start

```bash
# Clone on your Ubuntu VM (after completing INSTALLATION_GUIDE.md)
git clone https://github.com/Nirmal-Yash/wifi-validation-framework.git
cd wifi-validation-framework

# Setup Python environment
python3 -m venv wifi-venv
source wifi-venv/bin/activate
pip install -r requirements.txt

# Update configs/devices.yaml with your lab VM IPs

# Run all tests
pytest tests/ -v --html=results/reports/report.html

# Or use the run script
chmod +x run_all.sh
./run_all.sh
```

## Regression Workflow

```bash
# 1. Run tests on Firmware v1.0 and save baseline
pytest tests/ -v --firmware-version=v1.0
python regression/baseline_runner.py --version v1.0

# 2. Simulate firmware upgrade with deliberate bug
python regression/fw_simulator.py --version v2.0 --bug dns

# 3. Re-run tests on v2.0
pytest tests/ -v --firmware-version=v2.0

# 4. Generate diff report
python regression/diff_engine.py --version v1.0
# Output: results/reports/diff_report.html

# 5. View dashboard
python dashboard/app.py
# Open http://localhost:5000
```

## Test Suite

| Test File | Marker | Validates |
|---|---|---|
| `test_dhcp.py` | smoke | Client VM receives DHCP IP |
| `test_ssid.py` | smoke | Configured SSID visible in scan |
| `test_auth.py` | regression | WPA2 authentication completed |
| `test_dns.py` | smoke | DNS hostname resolution |
| `test_ping.py` | perf | Packet loss and latency thresholds |
| `test_throughput.py` | perf | iperf3 bandwidth above minimum |
| `test_packet_capture.py` | regression | DHCP packets in pcap |
| `test_fault_injection.py` | regression | Link down/up recovery |

Run by marker:

```bash
pytest -m smoke -v        # Quick checks
pytest -m regression -v   # Full regression
pytest -m perf -v         # Performance tests
```

## Project Structure

```
wifi-validation-framework/
├── configs/           # devices.yaml, test_params.yaml, topology.yaml
├── templates/         # Jinja2 router and hostapd config templates
├── lib/               # connector, traffic, capture, db_helper
├── tests/             # Pytest test suite
├── regression/        # baseline, diff engine, fw simulator
├── dashboard/         # Flask web UI (localhost:5000)
├── docs/              # INSTALLATION_GUIDE.md
├── results/           # reports, captures, SQLite DB (gitignored)
├── requirements.txt
├── pytest.ini
└── run_all.sh
```

## Configuration

Edit these files to match your lab:

- **`configs/devices.yaml`** — SSH IPs, usernames, passwords for all VMs
- **`configs/test_params.yaml`** — SSID, thresholds, firmware versions
- **`configs/topology.yaml`** — Lab node layout documentation

## Tech Stack

| Tool | Purpose |
|---|---|
| GNS3 + FRR | Virtual network lab |
| hostapd | Software WiFi access point |
| Netmiko | SSH automation |
| Pytest | Test framework |
| PyShark / tcpdump | Packet capture and analysis |
| iperf3 | Throughput measurement |
| SQLite | Test result storage |
| Flask | Web dashboard |
| Jinja2 | Config template rendering |

## Documentation

- **[Installation Guide](docs/INSTALLATION_GUIDE.md)** — Complete manual setup for Ubuntu VM, GNS3, Docker, hostapd, and lab topology

## Team

| Person | Focus |
|---|---|
| Person A | Lab setup, router config, Netmiko SSH, packet capture |
| Person B | Pytest tests, SQLite, Flask dashboard, reports |

## License

MIT — free for academic and personal use.
