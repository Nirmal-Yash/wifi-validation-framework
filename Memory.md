# NetForge Project Memory & Evolution Log

## Core Objective
To design and implement a production-grade automated regression testing framework for Wi-Fi and network devices, operating without physical hardware requirements via Linux kernel simulation.

## Evolutionary Phases
*   **Phases 1-3 (Architecture Pivot):** Bypassed heavy GNS3 QEMU limits. Deployed `mac80211_hwsim` and `netns` for Layer 1 execution, creating virtual radios in memory that interface with `hostapd` via Netlink sockets.
*   **Phases 4-9 (Test Engine Construction):** Built the Pytest execution engine with thread-safe fixtures. Integrated asynchronous `tcpdump` sniffing and Scapy for evidence-based L2/L3 assertions (DHCP and WPA3-SAE).
*   **Phases 10-15 (Regression & NOC Dashboard):** Engineered the `diff_engine.py` using SQLite to track baseline metrics and detect silent firmware regressions. Built a Flask-based modern UI/UX NOC dashboard for telemetry visualization.
*   **Phase 16 (GNS3 Integration & UX Polish):** Connected the Python backend directly to the GNS3 Server API via `gns3fy`. Overhauled the frontend with a glassmorphic dark theme, converted tooltips to native Vis.js rendering, and upgraded the configuration modal to a strictly validated full JSON editor.
*   **Phases 17-20 (Enterprise CI/CD Transition):** Prepared the framework for enterprise deployments. Simulated Wi-Fi 7 MLO (Multi-Link Operation) failovers, tested TR-369 (USP) remote radio disabling, automated A/B partition firmware swaps, and constructed `hil_abstractor.py` to route SSH commands to physical Tier 2 hardware via Netmiko. Hardened GitHub Actions pipeline for Azure kernel compatibility.
