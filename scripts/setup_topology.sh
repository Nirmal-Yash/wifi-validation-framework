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
CERT_DIR="$ROOT/config/certs"

for cmd in ip iw modprobe hostapd hostapd_cli wpa_supplicant wpa_cli dnsmasq dhclient tcpdump ethtool openssl; do
  command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd"; exit 2; }
done

mkdir -p "$ROOT/config" "$ROOT/artifacts/pcaps" "$ROOT/artifacts/logs" "$CERT_DIR" /run/hostapd /run/wpa_supplicant

log() { printf '[NetForge] %s\n' "$*"; }
run_cmd() { log "RUN: $*"; "$@"; }

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
      while read -r pid; do [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true; done < <(ip netns pids "$ns" 2>/dev/null || true)
      sleep 0.2
      while read -r pid; do [[ -n "$pid" ]] && kill -KILL "$pid" 2>/dev/null || true; done < <(ip netns pids "$ns" 2>/dev/null || true)
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
  done < <(iw dev | awk '/^phy#/ {gsub("phy#", "", $1); phy=$1} /^[[:space:]]+Interface / {print phy, $2}')
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
      hwsim_inventory >&2 || true
      exit 5
    fi
    sleep 1
  fi
  [[ -z "$(hwsim_inventory)" ]] || { echo "ERROR: hwsim interfaces remain after module removal." >&2; hwsim_inventory >&2; exit 6; }
  log "Loading a fresh mac80211_hwsim instance with exactly $HWSIM_RADIOS radios (P2P disabled)"
  modprobe mac80211_hwsim radios="$HWSIM_RADIOS" support_p2p_device=0
  for _ in {1..20}; do
    [[ $(hwsim_inventory | wc -l) -eq "$HWSIM_RADIOS" ]] && return 0
    sleep 0.25
  done
  echo "ERROR: mac80211_hwsim did not create exactly $HWSIM_RADIOS interfaces." >&2
  hwsim_inventory >&2
  exit 7
}

provision_enterprise_certs() {
  rm -f "$CERT_DIR"/ca.key "$CERT_DIR"/ca.pem "$CERT_DIR"/server.key "$CERT_DIR"/server.csr "$CERT_DIR"/server.pem "$CERT_DIR"/ca.srl
  umask 077
  openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 2 -keyout "$CERT_DIR/ca.key" -out "$CERT_DIR/ca.pem" -subj '/CN=NetForge Test CA' >/dev/null 2>&1
  openssl req -newkey rsa:2048 -nodes -sha256 -keyout "$CERT_DIR/server.key" -out "$CERT_DIR/server.csr" -subj '/CN=NetForge-Enterprise' >/dev/null 2>&1
  openssl x509 -req -sha256 -days 2 -in "$CERT_DIR/server.csr" -CA "$CERT_DIR/ca.pem" -CAkey "$CERT_DIR/ca.key" -CAcreateserial -out "$CERT_DIR/server.pem" -extfile <(printf 'basicConstraints=CA:FALSE\nsubjectAltName=DNS:NetForge-Enterprise') >/dev/null 2>&1
  rm -f "$CERT_DIR/server.csr" "$CERT_DIR/ca.srl"
}

cleanup_on_error() {
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "[NetForge] SETUP FAILED (exit $rc); cleaning partial topology" >&2
    remove_lab_namespaces || true
    modprobe -r mac80211_hwsim 2>/dev/null || true
  fi
  exit "$rc"
}
trap cleanup_on_error EXIT

reset_hwsim
mapfile -t inventory < <(hwsim_inventory | sort -k2,2V)
[[ ${#inventory[@]} -eq 3 ]] || { echo "ERROR: Expected exactly 3 hwsim interface/PHY pairs." >&2; printf '%s\n' "${inventory[@]:-none}" >&2; exit 8; }
read -r AP_PHY AP_SOURCE <<<"${inventory[0]}"
read -r CLIENT_PHY CLIENT_SOURCE <<<"${inventory[1]}"
read -r MON_PHY MON_SOURCE <<<"${inventory[2]}"
log "Deterministic role map: phy$AP_PHY/$AP_SOURCE -> $NS_AP; phy$CLIENT_PHY/$CLIENT_SOURCE -> $NS_CLIENT; phy$MON_PHY/$MON_SOURCE -> $NS_MON"

run_cmd ip netns add "$NS_AP"
run_cmd ip netns add "$NS_CLIENT"
run_cmd ip netns add "$NS_MON"

move_phy() {
  local phy="$1" ns="$2" error_file=/tmp/netforge_phy_error
  rm -f "$error_file"
  for attempt in 1 2 3 4 5; do
    log "Moving phy$phy into $ns (attempt $attempt)"
    if iw phy "phy$phy" set netns name "$ns" 2>"$error_file"; then return 0; fi
    if grep -qi 'busy' "$error_file"; then sleep 1; release_hwsim_consumers; continue; fi
    break
  done
  echo "ERROR: phy$phy could not be moved into $ns." >&2
  cat "$error_file" >&2 || true
  fuser -v "/sys/class/ieee80211/phy$phy" 2>&1 || true
  iw phy "phy$phy" info 2>&1 | head -80 || true
  hwsim_inventory >&2 || true
  exit 10
}

move_phy "$AP_PHY" "$NS_AP"
move_phy "$CLIENT_PHY" "$NS_CLIENT"
move_phy "$MON_PHY" "$NS_MON"
run_cmd ip netns exec "$NS_AP" iw dev | grep -q "Interface $AP_SOURCE"
run_cmd ip netns exec "$NS_CLIENT" iw dev | grep -q "Interface $CLIENT_SOURCE"
run_cmd ip netns exec "$NS_MON" iw dev | grep -q "Interface $MON_SOURCE"
run_cmd ip netns exec "$NS_AP" ip link set "$AP_SOURCE" name "$AP_IF"
run_cmd ip netns exec "$NS_CLIENT" ip link set "$CLIENT_SOURCE" name "$CLIENT_IF"
run_cmd ip netns exec "$NS_MON" ip link set "$MON_SOURCE" name "$MON_IF"
run_cmd ip netns exec "$NS_AP" ip link set lo up
run_cmd ip netns exec "$NS_CLIENT" ip link set lo up
run_cmd ip netns exec "$NS_MON" ip link set lo up
run_cmd ip netns exec "$NS_AP" ip link set "$AP_IF" down
run_cmd ip netns exec "$NS_CLIENT" ip link set "$CLIENT_IF" down
run_cmd ip netns exec "$NS_MON" ip link set "$MON_IF" down
run_cmd ip netns exec "$NS_AP" iw dev "$AP_IF" set type __ap
run_cmd ip netns exec "$NS_CLIENT" iw dev "$CLIENT_IF" set type managed
run_cmd ip netns exec "$NS_MON" iw dev "$MON_IF" set type monitor
run_cmd ip netns exec "$NS_AP" ip link set "$AP_IF" up
run_cmd ip netns exec "$NS_CLIENT" ip link set "$CLIENT_IF" up
run_cmd ip netns exec "$NS_MON" ip link set "$MON_IF" up
run_cmd ip netns exec "$NS_AP" ip addr replace 192.168.50.1/24 dev "$AP_IF"

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
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=Password123!
EOF

cat > "$ROOT/config/client.conf" <<EOF
ctrl_interface=/run/wpa_supplicant
update_config=0
country=IN
network={
    ssid="NetForge_Test"
    key_mgmt=WPA-PSK
    psk="Password123!"
    scan_ssid=1
}
EOF

provision_enterprise_certs
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
ca_cert=$CERT_DIR/ca.pem
server_cert=$CERT_DIR/server.pem
private_key=$CERT_DIR/server.key
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
    ca_cert="$CERT_DIR/ca.pem"
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

run_cmd ip netns exec "$NS_AP" ip link show "$AP_IF"
run_cmd ip netns exec "$NS_CLIENT" ip link show "$CLIENT_IF"
run_cmd ip netns exec "$NS_MON" ip link show "$MON_IF"
run_cmd ip netns exec "$NS_AP" ip -4 addr show dev "$AP_IF" | grep -q '192.168.50.1/24'
trap - EXIT
printf '%s\n' "NetForge Tier-1 topology ready" "  AP: $NS_AP/$AP_IF" "  Client: $NS_CLIENT/$CLIENT_IF" "  Monitor: $NS_MON/$MON_IF" "  AP: 192.168.50.1/24" "  AP channel: hostapd-managed (6)" "  Baseline security: WPA2-PSK" "  Enterprise TLS: $CERT_DIR"
