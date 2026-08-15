#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/teardown_topology.sh"
  exit 1
fi

for proc in hostapd wpa_supplicant dnsmasq dhclient iperf3 tcpdump; do
  pkill -x "$proc" 2>/dev/null || true
done

for ns in ap_ns client_ns monitor_ns router_ns switch_ns; do
  ip netns del "$ns" 2>/dev/null || true
done

# Only the isolated NetForge VM should run this teardown because removing the
# hwsim module removes its virtual radios from the host.
modprobe -r mac80211_hwsim 2>/dev/null || true

echo "NetForge Tier-1 topology cleared."
