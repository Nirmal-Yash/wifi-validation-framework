#!/bin/bash
set -e
echo "[*] Initializing Enterprise Topology..."

# 1. Create Namespaces
sudo ip netns add router_ns
sudo ip netns add switch_ns
sudo ip netns add ap_ns
sudo ip netns add client_ns
sudo ip netns add monitor_ns

# 2. Virtual Ethernet Links
sudo ip link add veth_rtr type veth peer name veth_sw_up
sudo ip link add veth_sw_down type veth peer name veth_ap

# 3. Assign Interfaces
sudo ip link set veth_rtr netns router_ns
sudo ip link set veth_sw_up netns switch_ns
sudo ip link set veth_sw_down netns switch_ns
sudo ip link set veth_ap netns ap_ns

# 4. Virtual Switch
sudo ip netns exec switch_ns ip link add name br0 type bridge
sudo ip netns exec switch_ns ip link set veth_sw_up master br0
sudo ip netns exec switch_ns ip link set veth_sw_down master br0
sudo ip netns exec switch_ns ip link set veth_sw_up up
sudo ip netns exec switch_ns ip link set veth_sw_down up
sudo ip netns exec switch_ns ip link set br0 up

# 5. Core Router
sudo ip netns exec router_ns ip link set lo up
sudo ip netns exec router_ns ip link set veth_rtr up
sudo ip netns exec router_ns ip link add link veth_rtr name veth_rtr.10 type vlan id 10
sudo ip netns exec router_ns ip addr add 10.0.10.1/24 dev veth_rtr.10
sudo ip netns exec router_ns ip link set veth_rtr.10 up

# 6. Access Point
sudo ip netns exec ap_ns ip link set lo up
sudo ip netns exec ap_ns ip link set veth_ap up
sudo ip netns exec ap_ns ip link add link veth_ap name veth_ap.10 type vlan id 10
sudo ip netns exec ap_ns ip link set veth_ap.10 up

echo "[+] Enterprise topology constructed."
