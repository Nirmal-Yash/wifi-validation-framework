#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/teardown_topology.sh"
  exit 1
fi

log() { printf '[NetForge] %s\n' "$*"; }

for proc in hostapd wpa_supplicant dnsmasq dhclient iperf3 tcpdump; do
  pkill -x "$proc" 2>/dev/null || true
done

while read -r unit; do
  [[ -n "$unit" ]] && systemctl stop "$unit" 2>/dev/null || true
done < <(systemctl list-units --all --no-legend 'wpa_supplicant*' 2>/dev/null | awk '{print $1}')

for ns in ap_ns client_ns monitor_ns router_ns switch_ns; do
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

if lsmod | awk '{print $1}' | grep -Fxq mac80211_hwsim; then
  if ! modprobe -r mac80211_hwsim 2>/tmp/netforge_teardown_error; then
    echo "ERROR: mac80211_hwsim could not be unloaded; the virtual radios are still busy." >&2
    cat /tmp/netforge_teardown_error >&2 || true
    echo "Inspect consumers with: sudo fuser -v /sys/class/ieee80211/phy*" >&2
    exit 2
  fi
fi

sleep 1
log "Tier-1 topology cleared; no NetForge hwsim radios remain."
