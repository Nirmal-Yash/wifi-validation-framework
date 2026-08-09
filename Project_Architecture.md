# NetForge System Architecture

## Overview
NetForge is a 7-Layer QA pipeline that mirrors industry-standard test environments used by SDET teams. It operates at Layer 1 using `mac80211_hwsim`, creating virtual Wi-Fi radios in memory that interface directly with `hostapd` via Netlink sockets.

## File System Tree

wifi-validation-framework/
├── config/
│   ├── devices.yaml         # Namespace, interface, and spatial coordinates
│   └── test_params.yaml     # Pass/Fail thresholds (throughput, latency)
├── db/
│   ├── results.db           # SQLite metrics and state transitions
│   └── schema.sql           # Database initialization schema
├── engine/
│   ├── diff_engine.py       # Detects silent Pass-to-Fail regressions
│   ├── fw_simulator.py      # Automates dual-bank (A/B) firmware flashing
│   ├── hil_abstractor.py    # Routes commands to virtual netns or physical hardware
│   └── topology_importer.py # Parses GNS3 geometries and SVG configs
├── dashboard/
│   ├── app.py               # Flask Control Plane & GNS3 API
│   └── templates/           # Void-Amber UI (base.html, dashboard, topology, history)
├── scripts/
│   ├── setup_topology.sh    # Provisions mac80211_hwsim and isolates netns bubbles
│   └── teardown_topology.sh # Destroys namespaces and clears kernel modules
└── tests/
    ├── conftest.py          # Master Pytest fixture & asynchronous tcpdump hook
    ├── test_auth.py         # Validates WPA3-SAE association handshakes
    ├── test_dhcp.py         # Validates IP allocations via Scapy parsing
    ├── test_throughput.py   # Validates iperf3 data-plane speed metrics
    ├── test_mlo_failover.py # Simulates Wi-Fi 7 interface crashes
    └── test_usp_telemetry.py# Validates TR-369 remote administration

####  Architectural Layers

    Foundation (Virtualization): mac80211_hwsim and Linux netns.

    Configuration: YAML files and .conf payloads mapped via GNS3 JSON.

    Connectivity: Native subprocess execution inside network namespaces.

    Traffic Analysis: iperf3 for payload, tcpdump for async PCAP generation.

    Execution: Pytest fixtures managing the network state machine.

    Intelligence: SQLite + Pandas evaluating baseline vs. candidate firmware.

    Output: Flask-driven NOC visualization via Vis.js.

