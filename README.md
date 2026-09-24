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

## Target platform

The final architecture adds:

- Run and Attempt lifecycle;
- TestResult, Metric, Sample and Artifact model;
- Lab Health;
- evidence completeness;
- statistical validation;
- protocol transaction correlation;
- WiFi telemetry;
- DeviceAdapter/FirmwareAdapter;
- authenticated API;
- CI release gates;
- NetRegress Runner;
- NetRegress Cloud.

## Documentation

Start with:

1. docs/ARCHITECTURE_DECISIONS.md
2. docs/IMPLEMENTATION_PLAN.md
3. docs/BUSINESS_LOGIC.md
4. docs/TECHNICAL_ARCHITECTURE.md
5. docs/DATA_MODEL_AND_APIS.md
6. docs/EXECUTION_AND_ADAPTERS.md
7. docs/SECURITY_AND_SAAS.md
8. docs/TESTING_AND_OPERATIONS.md
9. docs/FRONTEND_DESIGN.md
10. docs/DOCUMENTATION_TRACEABILITY.md

Operational references remain:

- docs/WIFI_LAB_REPRODUCTION.md
- docs/INSTALLATION_GUIDE.md

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

## Roadmap

Phase 0: baseline protection.

Phase 1: Run/Evidence foundation.

Phase 1S: security gate.

Phase 2: Lab Health.

Phase 3: statistical rigor.

Phase 4: functional WiFi expansion.

Phase 5: protocol evidence.

Phase 6: WiFi telemetry.

Phase 7: regression intelligence.

Phase 8: dashboard 2.0.

Phase 9: device/firmware adapters.

Phase 10a: internal CI release gate.

Phase 10b: NetRegress Cloud.

Phase 11: PostgreSQL after real concurrent Cloud workload.

## License

MIT — current repository remains suitable for academic and personal development while the production architecture is built incrementally.

## Iteration 17

Device and firmware control is now adapter-backed. The Runner supports profile-driven Linux/OpenWrt device access, SHA-256 firmware validation, optional signature verification, SFTP transfer, explicit firmware authorization, staged lifecycle auditing and deterministic fake adapters.

### Internal CI release gate

GitHub-hosted CI validates the hardware-free core and release-policy contracts on every push/PR. The protected GNS3/mac80211_hwsim suite is separated into an explicit self-hosted lab dispatch so generic CI never misrepresents lab availability as product validation.

## Iteration 19

The Runner now survives Cloud outages with a durable local synchronization queue. Terminal Runs are snapshotted locally and can be synchronized later through an outbound HTTPS transport using deterministic idempotency keys.