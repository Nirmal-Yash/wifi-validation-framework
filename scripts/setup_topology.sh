#!/bin/bash
# scripts/setup_topology.sh
set -e

echo "[*] Loading Wi-Fi simulator module (radios=3)..."
modprobe mac80211_hwsim radios=3
# CRITICAL: Allow the kernel time to register the new interfaces before manipulating them
sleep 3  

echo "[*] Creating Network Namespaces..."
ip netns add ap_ns
ip netns add client_ns
ip netns add monitor_ns

echo "[*] Mapping physical wireless radios..."
# Identify the physical ID of the newly created interfaces
phy0=$(iw dev wlan0 info | grep wiphy | awk '{print "phy"$2}')
phy1=$(iw dev wlan1 info | grep wiphy | awk '{print "phy"$2}')
phy2=$(iw dev wlan2 info | grep wiphy | awk '{print "phy"$2}')

echo "[*] Assigning Interfaces: $phy0 -> ap_ns | $phy1 -> client_ns | $phy2 -> monitor_ns"
iw phy $phy0 set netns name ap_ns
iw phy $phy1 set netns name client_ns
iw phy $phy2 set netns name monitor_ns

echo "[*] Activating AP and Client Interfaces..."
ip netns exec ap_ns ip link set lo up
ip netns exec ap_ns ip link set wlan0 up

ip netns exec client_ns ip link set lo up
ip netns exec client_ns ip link set wlan1 up

echo "[*] Configuring Monitor Mode Interface for Sniffing..."
# FIX: Ensure interface is DOWN before changing type, then bring UP
ip netns exec monitor_ns ip link set lo up
ip netns exec monitor_ns ip link set wlan2 down
ip netns exec monitor_ns iw dev wlan2 set type monitor
ip netns exec monitor_ns ip link set wlan2 up

echo "[+] Virtual Topology Environment Provisioned Successfully!"
