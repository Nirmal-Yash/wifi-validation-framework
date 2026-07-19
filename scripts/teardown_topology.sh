#!/bin/bash
# scripts/teardown_topology.sh
set -e

echo "[*] Terminating active framework processes..."
sudo killall hostapd wpa_supplicant dnsmasq iperf3 tcpdump 2>/dev/null || true

echo "[*] Removing network namespaces..."
sudo ip netns del ap_ns 2>/dev/null || true
sudo ip netns del client_ns 2>/dev/null || true
sudo ip netns del monitor_ns 2>/dev/null || true

echo "[*] Unloading Wi-Fi simulator module..."
sudo rmmod mac80211_hwsim 2>/dev/null || true

echo "[+] Localized virtual environment successfully cleared."
