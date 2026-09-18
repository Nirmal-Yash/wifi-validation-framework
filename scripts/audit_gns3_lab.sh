#!/usr/bin/env bash
# Pre-flight audit for GNS3 WiFi lab (run on Ubuntu VM from repo root).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
OUT="${REPO_ROOT}/results/setup-logs/audit-$(date +%Y%m%d-%H%M%S).txt"
mkdir -p "$(dirname "$OUT")"
exec > >(tee "$OUT") 2>&1

echo "=== WiFi Lab Audit ==="
echo "Date: $(date -Is)"
echo "Host: $(uname -a)"
echo

echo "--- Git ---"
git status -sb || true
git branch -vv || true
git remote -v || true
echo

echo "--- Docker GNS3 containers ---"
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | grep -iE 'gns3|frr|hostapd|wifi|monitor' || true
echo

echo "--- Libvirt default / virbr0 ---"
virsh net-info default 2>/dev/null || echo "virsh net-info default: unavailable"
ip -4 addr show virbr0 2>/dev/null || echo "virbr0: not found"
virsh net-dhcp-leases default 2>/dev/null || true
echo

echo "--- mac80211_hwsim ---"
lsmod | grep mac80211_hwsim || echo "mac80211_hwsim not loaded"
sudo iw phy 2>/dev/null || iw phy 2>/dev/null || true
echo

echo "--- GNS3 API (if credentials in env) ---"
if [[ -n "${GNS3_API_USER:-}" && -n "${GNS3_API_PASSWORD:-}" ]]; then
  curl -sS -f -u "${GNS3_API_USER}:${GNS3_API_PASSWORD}" \
    "${GNS3_API:-http://127.0.0.1:3080}/v2/version" || echo "GNS3 API unreachable"
else
  echo "Set GNS3_API_USER and GNS3_API_PASSWORD to probe API."
fi
echo

echo "Audit log: $OUT"
