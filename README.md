# NetRegress Validation Engine

NetRegress is an evidence-driven WiFi/network validation and regression engine. This repository is the Runner/Core layer that executes real validation against the GNS3/mac80211_hwsim lab today and is designed to control physical devices through adapters later.

## Protected behavioral baseline

~~~text
436026eba597b2c6ae2e291a9cd8054b70ebbf7c
11 / 11 real-lab tests PASS
~~~

That baseline protects the current network behavior while the application architecture is refactored around Run-scoped evidence.

## Current capabilities

- real WPA2 state validation;
- DHCP lease and timing validation;
- DNS resolution;
- ping, loss and latency;
- iperf3 throughput;
- real DHCP PCAP capture;
- fault injection and recovery;
- SQLite persistence;
- firmware-version comparison;
- Flask dashboard;
- automated GNS3 laboratory provisioning.

## Canonical documentation

Read the canonical documents in this order:

1. docs/01_DEVELOPMENT_PLAN_AND_ROADMAP.md — development order, historical phases and roadmap
2. docs/02_SYSTEM_ARCHITECTURE_DATA_API.md — backend architecture, data model and API
3. docs/03_TRACEABILITY_AND_SYSTEM_READINESS.md — traceability, audit and readiness
4. docs/04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md — installation, exact lab reproduction and operations
5. docs/05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md — architecture decisions and business invariants

Supporting contracts remain separate:
- docs/EXECUTION_AND_ADAPTERS.md
- docs/SECURITY_AND_SAAS.md
- docs/FRONTEND_DESIGN.md
- docs/PRD.md
- docs/AGENT_CONTEXT.md

Legacy documentation paths remain as compatibility pointers to the canonical documents above.

## Current quick start

~~~bash
python3 -m venv wifi-venv
source wifi-venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v --firmware-version=v1.0
~~~

## Lab provisioning

~~~bash
./wifi_lab_reprovision_robust.sh
./wifi_lab_reprovision_robust.sh --setup-only
./wifi_lab_reprovision_robust.sh --repro-test
~~~

Run the provisioning script as the normal Ubuntu user, not with sudo.

## Engineering rules

- develop directly on main;
- no feature branches;
- one architectural slice per commit;
- preserve existing pytest node IDs;
- never weaken assertions to make a test pass;
- never use synthetic traffic in real validation;
- never convert lab failure into product failure;
- never return PASS when required evidence failed;
- keep runtime results gitignored.

## Release verification

~~~bash
python scripts/netregress_release.py verify
python scripts/netregress_release.py doctor
python scripts/netregress_release.py manifest
~~~

The release manifest is source-readiness evidence. It does not substitute for protected GNS3/mac80211_hwsim execution evidence.
