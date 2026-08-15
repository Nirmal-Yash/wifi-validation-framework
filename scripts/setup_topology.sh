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
HWSIM_RADIOS=3

for cmd in ip iw modprobe hostapd wpa_supplicant dnsmasq dhclient tcpdump ethtool; do
  command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd"; exit 2; }
done

mkdir -p "$ROOT/config" "$ROOT/artifacts/pcaps" /run/hostapd /run/wpa_supplicant

log() { printf '[NetForge] %s\n' "$*"; }

stop_matching_units() {
  local unit
  while read -r unit; do
    [[ -n "$unit" ]] || continue
    systemctl stop "$unit" 2>/dev/null || true
  done < <(systemctl list-units --all --no-legend 'wpa_supplicant*' 2>/dev/null | awk '{print $1}')
}

stop_lab_processes() {
  for proc in hostapd dnsmasq wpa_supplicant dhclient iperf3 tcpdump; do
    pkill -x "$proc" 2>/dev/null || true
  done
  stop_matching_units
  sleep 1
}

remove_lab_namespaces() {
  local ns pid
  for ns in "$NS_AP" "$NS_CLIENT" "$NS_MON" router_ns switch_ns; do
    if ip netns list | awk '{print $1}' | grep -Fxq "$ns"; then
      while read -r pid; do
        [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true
      done < <(ip netns pids "$ns" 2>/dev/null || true)
      sleep 0.2
      while read -r pid; do
        [[ -n "$pid" ]] && kill -KILL "$pid" 2>/dev/null || true
      done < <(ip netns pids "$ns" 2>/dev/null || true)
      ip netns del "$ns" 2>/dev/null || true
    fi
  done
}

hwsim_inventory() {
  local iface driver phy
  while read -r phy iface; do
    [[ -n "$phy" && -n "$iface" ]] || continue
    driver="$(ethtool -i "$iface" 2>/dev/null | awk -F': ' '$1=="driver" {print $2; exit}')"
    [[ "$driver" == "mac80211_hwsim" ]] || continue
    [[ "$iface" =~ ^wlan[0-9]+$ ]] || continue
    printf '%s %s\n' "$phy" "$iface"
  done < <(
    iw dev | awk '
      /^phy#/ {gsub("phy#", "", $1); phy=$1}
      /^[[:space:]]+Interface / {print phy, $2}
    '
  )
}

release_hwsim_consumers() {
  local iface
  while read -r _ iface; do
    [[ -n "$iface" ]] || continue
    if command -v nmcli >/dev/null 2>&1; then
      nmcli device disconnect "$iface" >/dev/null 2>&1 || true
      nmcli device set "$iface" managed no >/dev/null 2>&1 || true
    fi
    ip link set "$iface" down 2>/dev/null || true
  done < <(hwsim_inventory)
  stop_matching_units
  sleep 1
}

reset_hwsim() {
  log "Stopping NetForge daemons and releasing hwsim consumers"
  stop_lab_processes
  remove_lab_namespaces
  release_hwsim_consumers

  if lsmod | awk '{print $1}' | grep -Fxq mac80211_hwsim; then
    log "Removing stale mac80211_hwsim radios"
    if ! modprobe -r mac80211_hwsim 2>/tmp/netforge_hwsim_remove_error; then
      echo "ERROR: mac80211_hwsim is still busy and cannot be reset." >&2
      cat /tmp/netforge_hwsim_remove_error >&2 || true
      echo "Current hwsim inventory:" >&2
      hwsim_inventory >&2 || true
      echo "Potential consumers:" >&2
      for iface in $(hwsim_inventory | awk '{print $2}'); do
        fuser -v "/sys/class/net/$iface" 2>&1 || true
        nmcli device status 2>/dev/null | grep -F "$iface" || true
      done
      echo "Run: sudo ./scripts/teardown_topology.sh and retry." >&2
      exit 5
    fi
    sleep 1
  fi

  if [[ -n "$(hwsim_inventory)" ]]; then
    echo "ERROR: hwsim interfaces remain after module removal." >&2
    hwsim_inventory >&2 || true
    exit 6
  fi

  log "Loading a fresh mac80211_hwsim instance with exactly $HWSIM_RADIOS radios"
  modprobe mac80211_hwsim radios="$HWSIM_RADIOS"
  for _ in {1..20}; do
    [[ $(hwsim_inventory | wc -l) -eq "$HWSIM_RADIOS" ]] && return 0
    sleep 0.25
  done
  echo "ERROR: mac80211_hwsim did not create exactly $HWSIM_RADIOS interfaces." >&2
  hwsim_inventory >&2 || true
  exit 7
}

reset_hwsim

mapfile -t inventory < <(hwsim_inventory | sort -k2,2V)
if [[ ${#inventory[@]} -ne 3 ]]; then
  echo "ERROR: Expected exactly 3 hwsim interface/PHY pairs." >&2
  printf '%s\n' "${inventory[@]:-none}" >&2
  exit 8
fi

read -r AP_PHY AP_SOURCE <<<"${inventory[0]}"
read -r CLIENT_PHY CLIENT_SOURCE <<<"${inventory[1]}"
read -r MON_PHY MON_SOURCE <<<"${inventory[2]}"

[[ "$AP_SOURCE" == "$AP_IF" && "$CLIENT_SOURCE" == "$CLIENT_IF" && "$MON_SOURCE" == "$MON_IF" ]] || {
  echo "ERROR: Fresh hwsim naming is not wlan0/wlan1/wlan2: $AP_SOURCE/$CLIENT_SOURCE/$MON_SOURCE" >&2
  exit 9
}

log "Deterministic radio map: phy$AP_PHY/$AP_SOURCE -> $NS_AP; phy$CLIENT_PHY/$CLIENT_SOURCE -> $NS_CLIENT; phy$MON_PHY/$MON_SOURCE -> $NS_MON"

ip netns add "$NS_AP"
ip netns add "$NS_CLIENT"
ip netns add "$NS_MON"

move_phy() {
  local phy="$1" ns="$2"
  local error_file=/tmp/netforge_phy_error
  rm -f "$error_file"
  for attempt in 1 2 3 4 5; do
    if iw phy "phy$phy" set netns name "$ns" 2>"$error_file"; then
      return 0
    fi
    if grep -qi 'busy' "$error_file"; then
      sleep 1
      release_hwsim_consumers
      continue
    fi
    break
  done
  echo "ERROR: phy$phy could not be moved into $ns." >&2
  cat "$error_file" >&2 || true
  echo "PHY ownership/state:" >&2
  fuser -v "/sys/class/ieee80211/phy$phy" 2>&1 || true
  iw phy "phy$phy" info 2>&1 | head -60 || true
  echo "Interface state:" >&2
  ip link show "$AP_SOURCE" "$CLIENT_SOURCE" "$MON_SOURCE" 2>&1 || true
  remove_lab_namespaces
  modprobe -r mac80211_hwsim 2>/dev/null || true
  exit 10
}

move_phy "$AP_PHY" "$NS_AP"
move_phy "$CLIENT_PHY" "$NS_CLIENT"
move_phy "$MON_PHY" "$NS_MON"

ip netns exec "$NS_AP" iw dev | grep -q "Interface $AP_SOURCE"
ip netns exec "$NS_CLIENT" iw dev | grep -q "Interface $CLIENT_SOURCE"
ip netns exec "$NS_MON" iw dev | grep -q "Interface $MON_SOURCE"

ip netns exec "$NS_AP" ip link set "$AP_SOURCE" name "$AP_IF"
ip netns exec "$NS_CLIENT" ip link set "$CLIENT_SOURCE" name "$CLIENT_IF"
ip netns exec "$NS_MON" ip link set "$MON_SOURCE" name "$MON_IF"

ip netns exec "$NS_AP" ip link set lo up
ip netns exec "$NS_CLIENT" ip link set lo up
ip netns exec "$NS_MON" ip link set lo up

# Configure all radio state while interfaces are DOWN. iw requires this ordering
# for reliable nl80211 operation and it avoids EBUSY during channel/type changes.
ip netns exec "$NS_AP" ip link set "$AP_IF" down
ip netns exec "$NS_CLIENT" ip link set "$CLIENT_IF" down
ip netns exec "$NS_MON" ip link set "$MON_IF" down

ip netns exec "$NS_AP" iw dev "$AP_IF" set type __ap
ip netns exec "$NS_AP" iw dev "$AP_IF" set channel 6
ip netns exec "$NS_CLIENT" iw dev "$CLIENT_IF" set type managed
ip netns exec "$NS_CLIENT" iw dev "$CLIENT_IF" set channel 6
ip netns exec "$NS_MON" iw dev "$MON_IF" set type monitor
ip netns exec "$NS_MON" iw dev "$MON_IF" set channel 6

ip netns exec "$NS_AP" ip link set "$AP_IF" up
ip netns exec "$NS_CLIENT" ip link set "$CLIENT_IF" up
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
