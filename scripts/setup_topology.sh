#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/setup_topology.sh"
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS_AP=ap_ns
NS_CLIENT=client_ns
NS_MON=monitor_ns
AP_IF=wlan0
CLIENT_IF=wlan1
MON_IF=wlan2

for cmd in ip iw modprobe hostapd wpa_supplicant dnsmasq dhclient tcpdump; do
  command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd"; exit 2; }
done

mkdir -p "$ROOT/config" "$ROOT/artifacts/pcaps"
for proc in hostapd dnsmasq wpa_supplicant dhclient iperf3; do pkill -x "$proc" 2>/dev/null || true; done
for ns in "$NS_AP" "$NS_CLIENT" "$NS_MON"; do ip netns del "$ns" 2>/dev/null || true; done

before="$(mktemp)"
after="$(mktemp)"
trap 'rm -f "$before" "$after"' EXIT

iw dev | awk '$1 == "Interface" {print $2}' | grep -E '^wlan[0-9]+$' | sort -u > "$before" || true

modprobe bonding
modprobe 8021q
modprobe -r mac80211_hwsim 2>/dev/null || true
modprobe mac80211_hwsim radios=3
sleep 2

iw dev | awk '$1 == "Interface" {print $2}' | grep -E '^wlan[0-9]+$' | sort -u > "$after" || true
mapfile -t radios < <(comm -13 "$before" "$after")

if [[ ${#radios[@]} -ne 3 ]]; then
  echo "ERROR: Expected exactly 3 new mac80211_hwsim interfaces, found ${#radios[@]}"
  echo "Detected new wlan interfaces: ${radios[*]:-none}"
  echo "Full wireless inventory:"
  iw dev || true
  exit 3
fi

for radio in "${radios[@]}"; do
  if ! ip link show "$radio" >/dev/null 2>&1; then
    echo "ERROR: Detected wireless interface '$radio' is not movable from the root namespace."
    exit 4
  fi
done

ip netns add "$NS_AP"
ip netns add "$NS_CLIENT"
ip netns add "$NS_MON"

ip link set "${radios[0]}" netns "$NS_AP"
ip link set "${radios[1]}" netns "$NS_CLIENT"
ip link set "${radios[2]}" netns "$NS_MON"

ip netns exec "$NS_AP" ip link set "${radios[0]}" name "$AP_IF"
ip netns exec "$NS_CLIENT" ip link set "${radios[1]}" name "$CLIENT_IF"
ip netns exec "$NS_MON" ip link set "${radios[2]}" name "$MON_IF"

ip netns exec "$NS_AP" ip link set lo up
ip netns exec "$NS_CLIENT" ip link set lo up
ip netns exec "$NS_MON" ip link set lo up
ip netns exec "$NS_AP" ip link set "$AP_IF" up
ip netns exec "$NS_CLIENT" ip link set "$CLIENT_IF" up
ip netns exec "$NS_MON" ip link set "$MON_IF" down
ip netns exec "$NS_MON" iw dev "$MON_IF" set type monitor
ip netns exec "$NS_MON" iw dev "$MON_IF" set channel 6
ip netns exec "$NS_MON" ip link set "$MON_IF" up
ip netns exec "$NS_AP" ip addr add 192.168.50.1/24 dev "$AP_IF"

cat > "$ROOT/config/ap.conf" <<EOF
ctrl_interface=/run/hostapd
interface=$AP_IF
driver=nl80211
ssid=NetForge_Test
hw_mode=g
channel=6
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=SAE WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=Password123!
sae_password=Password123!
sae_pwe=2
EOF

cat > "$ROOT/config/client.conf" <<EOF
ctrl_interface=/run/wpa_supplicant
update_config=0
country=IN
network={
    ssid="NetForge_Test"
    key_mgmt=SAE
    psk="Password123!"
    ieee80211w=2
}
EOF

cat > "$ROOT/config/hostapd_enterprise.conf" <<EOF
ctrl_interface=/run/hostapd
interface=$AP_IF
driver=nl80211
ssid=NetForge_Enterprise
hw_mode=g
channel=6
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-EAP
rsn_pairwise=CCMP
ieee8021x=1
eap_server=1
eap_user_file=$ROOT/config/hostapd.eap_user
EOF
cat > "$ROOT/config/hostapd.eap_user" <<EOF
* PEAP
"admin" PEAP "Password123!" [2]
EOF
cat > "$ROOT/config/wpa_supplicant_enterprise.conf" <<EOF
ctrl_interface=/run/wpa_supplicant
update_config=0
network={
    ssid="NetForge_Enterprise"
    key_mgmt=WPA-EAP
    eap=PEAP
    identity="admin"
    password="Password123!"
    phase2="auth=MSCHAPV2"
}
EOF

cat > "$ROOT/config/devices.yaml" <<EOF
nodes:
  ap:
    namespace: $NS_AP
    interface: $AP_IF
    config_path: config/ap.conf
    x: -250
    y: 0
  client:
    namespace: $NS_CLIENT
    interface: $CLIENT_IF
    config_path: config/client.conf
    x: 250
    y: 0
  monitor:
    namespace: $NS_MON
    interface: $MON_IF
    x: 0
    y: 180
target_environment:
  environment_type: localized_netns
  log_directory: artifacts/pcaps
EOF

ip netns exec "$NS_AP" ip link show "$AP_IF" >/dev/null
ip netns exec "$NS_CLIENT" ip link show "$CLIENT_IF" >/dev/null
ip netns exec "$NS_MON" ip link show "$MON_IF" >/dev/null
ip netns exec "$NS_AP" ip -4 addr show dev "$AP_IF" | grep -q '192.168.50.1/24'

printf '%s\n' "NetForge Tier-1 topology ready" "  AP: $NS_AP/$AP_IF" "  Client: $NS_CLIENT/$CLIENT_IF" "  Monitor: $NS_MON/$MON_IF" "  AP: 192.168.50.1/24"
