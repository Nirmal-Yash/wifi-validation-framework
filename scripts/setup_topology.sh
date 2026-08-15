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

for cmd in ip iw modprobe hostapd wpa_supplicant dnsmasq dhclient tcpdump ethtool; do
  command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd"; exit 2; }
done

mkdir -p "$ROOT/config" "$ROOT/artifacts/pcaps"

hard_cleanup() {
  for proc in hostapd dnsmasq wpa_supplicant dhclient iperf3; do
    pkill -x "$proc" 2>/dev/null || true
  done
  for ns in "$NS_AP" "$NS_CLIENT" "$NS_MON"; do
    ip netns del "$ns" 2>/dev/null || true
  done
}

hard_cleanup

hwsim_inventory() {
  local iface driver phy
  while read -r phy iface; do
    [[ -n "$phy" && -n "$iface" ]] || continue
    driver="$(ethtool -i "$iface" 2>/dev/null | awk -F': ' '$1=="driver" {print $2; exit}')"
    [[ "$driver" == "mac80211_hwsim" ]] || continue
    printf '%s %s\n' "$phy" "$iface"
  done < <(
    iw dev | awk '
      /^phy#/ {gsub("phy#", "", $1); phy=$1}
      /^[[:space:]]+Interface / {print phy, $2}
    '
  )
}

release_radio_consumers() {
  local iface
  while read -r _ iface; do
    [[ -n "$iface" ]] || continue
    if command -v nmcli >/dev/null 2>&1; then
      nmcli device disconnect "$iface" >/dev/null 2>&1 || true
      nmcli device set "$iface" managed no >/dev/null 2>&1 || true
    fi
    ip link set "$iface" down 2>/dev/null || true
    iw dev "$iface" set type managed 2>/dev/null || true
    ip link set "$iface" down 2>/dev/null || true
  done < <(hwsim_inventory)

  if command -v systemctl >/dev/null 2>&1; then
    systemctl stop wpa_supplicant.service 2>/dev/null || true
  fi
  sleep 2
}

mapfile -t inventory < <(hwsim_inventory)

if [[ ${#inventory[@]} -eq 0 ]]; then
  modprobe bonding
  modprobe 8021q
  modprobe mac80211_hwsim radios=3
  sleep 2
  mapfile -t inventory < <(hwsim_inventory)
else
  echo "Reusing existing mac80211_hwsim radios: $(printf '%s ' "${inventory[@]}")"
fi

if [[ ${#inventory[@]} -ne 3 ]]; then
  echo "ERROR: Expected exactly 3 mac80211_hwsim interfaces, found ${#inventory[@]}"
  printf '%s\n' "${inventory[@]:-none}"
  iw dev || true
  exit 3
fi

release_radio_consumers

mapfile -t phys < <(printf '%s\n' "${inventory[@]}" | awk '{print "phy" $1}' | sort -u)
mapfile -t radios < <(printf '%s\n' "${inventory[@]}" | awk '{print $2}')

if [[ ${#phys[@]} -ne 3 || ${#radios[@]} -ne 3 ]]; then
  echo "ERROR: Could not resolve three distinct hwsim PHY/interface pairs."
  printf 'PHYs: %s\n' "${phys[*]:-none}"
  printf 'Radios: %s\n' "${radios[*]:-none}"
  exit 4
fi

ip netns add "$NS_AP"
ip netns add "$NS_CLIENT"
ip netns add "$NS_MON"

move_phy() {
  local phy="$1" ns="$2"
  if iw phy "$phy" set netns name "$ns" 2>/tmp/netforge_phy_error; then
    return 0
  fi
  echo "ERROR: $phy could not be moved into $ns."
  cat /tmp/netforge_phy_error >&2 || true
  echo "Wireless owner check:" >&2
  fuser -v "/sys/class/ieee80211/$phy" 2>&1 || true
  echo "Current PHY state:" >&2
  iw phy "$phy" info 2>&1 | head -40 || true
  return 1
}

move_phy "${phys[0]}" "$NS_AP"
move_phy "${phys[1]}" "$NS_CLIENT"
move_phy "${phys[2]}" "$NS_MON"

ip netns exec "$NS_AP" iw dev | grep -q "Interface ${radios[0]}"
ip netns exec "$NS_CLIENT" iw dev | grep -q "Interface ${radios[1]}"
ip netns exec "$NS_MON" iw dev | grep -q "Interface ${radios[2]}"

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
ip netns exec "$NS_AP" ip addr replace 192.168.50.1/24 dev "$AP_IF"

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
