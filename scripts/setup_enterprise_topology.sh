#!/bin/bash
# scripts/setup_enterprise_topology.sh
set -e

echo "[*] Unloading old instances and clearing namespaces..."
sudo killall hostapd wpa_supplicant dnsmasq iperf3 tcpdump 2>/dev/null || true
sudo ip netns del ap_ns 2>/dev/null || true
sudo ip netns del client_ns1 2>/dev/null || true
sudo ip netns del client_ns2 2>/dev/null || true
sudo ip netns del monitor_ns 2>/dev/null || true
sudo ip netns del router_ns 2>/dev/null || true
sudo ip link del br-lan 2>/dev/null || true
sudo rmmod mac80211_hwsim 2>/dev/null || true

echo "[*] Loading Wi-Fi Simulator with 4 Radios (AP, Client1, Client2, Monitor)..."
sudo modprobe mac80211_hwsim radios=4

echo "[*] Creating Enterprise Network Namespaces..."
sudo ip netns add router_ns
sudo ip netns add ap_ns
sudo ip netns add client_ns1
sudo ip netns add client_ns2
sudo ip netns add monitor_ns

echo "[*] Mapping Wireless Radios to Namespaces..."
phy0=$(iw dev wlan0 info | grep wiphy | awk '{print "phy"$2}')
phy1=$(iw dev wlan1 info | grep wiphy | awk '{print "phy"$2}')
phy2=$(iw dev wlan2 info | grep wiphy | awk '{print "phy"$2}')
phy3=$(iw dev wlan3 info | grep wiphy | awk '{print "phy"$2}')

sudo iw phy $phy0 set netns name ap_ns
sudo iw phy $phy1 set netns name client_ns1
sudo iw phy $phy2 set netns name client_ns2
sudo iw phy $phy3 set netns name monitor_ns

echo "[*] Setting Up L2 Ethernet Bridge and veth Pairs..."
sudo ip link add br-lan type bridge
sudo ip link set br-lan up

# Create virtual ethernet pair between Router and Bridge
sudo ip link add veth_router type veth peer name veth_r_bridge
sudo ip link set veth_router netns router_ns
sudo ip link set veth_r_bridge master br-lan
sudo ip link set veth_r_bridge up

# Create virtual ethernet pair between AP and Bridge
sudo ip link add veth_ap type veth peer name veth_ap_bridge
sudo ip link set veth_ap netns ap_ns
sudo ip link set veth_ap_bridge master br-lan
sudo ip link set veth_ap_bridge up

echo "[*] Configuring Router and Interface IP Schemes..."
sudo ip netns exec router_ns ip link set lo up
sudo ip netns exec router_ns ip link set veth_router up
sudo ip netns exec router_ns ip addr add 10.0.10.1/24 dev veth_router

sudo ip netns exec ap_ns ip link set lo up
sudo ip netns exec ap_ns ip link set veth_ap up
sudo ip netns exec ap_ns ip link set wlan0 up
sudo ip netns exec ap_ns ip addr add 10.0.10.2/24 dev veth_ap

sudo ip netns exec client_ns1 ip link set lo up
sudo ip netns exec client_ns1 ip link set wlan1 up

sudo ip netns exec client_ns2 ip link set lo up
sudo ip netns exec client_ns2 ip link set wlan2 up

sudo ip netns exec monitor_ns ip link set lo up
sudo ip netns exec monitor_ns iw dev wlan3 set type monitor
sudo ip netns exec monitor_ns ip link set wlan3 up

echo "[*] Launching Gateway DHCP/DNS Services on Router..."
sudo ip netns exec router_ns dnsmasq \
  --interface=veth_router \
  --dhcp-range=10.0.10.50,10.0.10.150,255.255.255.0,12h \
  --dhcp-option=option:dns-server,1.1.1.1 \
  --no-daemon &

echo "[+] Enterprise Network Topology Successfully Created!"
