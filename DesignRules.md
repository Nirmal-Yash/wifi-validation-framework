# NetForge Design Rules & Standards

## 1. Stateless Environments
Tests must operate completely independently. The environment MUST be torn down and rebuilt by `conftest.py` between runs to guarantee clean cache states.

## 2. Evidence-Driven Assertions
Console output is insufficient for network validation. All L2/L3 tests (DHCP, WPA3, USP Telemetry) MUST leverage `scapy` to open `.pcap` artifacts and assert that the required packet structures traversed the virtual airwaves.

## 3. UI/UX Principles (Void-Amber Technical Brutalism)
*   **Palette:** Background `#131313`, Surfaces `#1f1f1f` / `#353535`, Sidebar `#0e0e0e`.
*   **Accents:** Primary `#ffb77d`, Primary Container `#ff8c00`, Error `#ffb4ab`.
*   **Typography:** 'JetBrains Mono' for system data, 'Courier Prime' for headers and badges, 'Space Mono' for brand markers.
*   **Geometry:** Sharp edges only (0px border-radius). Absolutely no soft shadows, gradients, or rounded corners. Buttons and panels must appear as rigid, flat terminal blocks.
*   **Interaction:** Tooltips (`title` attributes) must use native `\n` line breaks, not HTML tags, to ensure clean rendering in Vis.js canvases.

## 4. Hardware Abstraction
Test definitions must not contain hardcoded `sudo ip netns exec` commands. All execution logic must funnel through `hil_abstractor.py`.
