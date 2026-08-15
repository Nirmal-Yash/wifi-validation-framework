#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this script as the normal project user, not root."
  exit 1
fi

source "$ROOT/wifi-venv/bin/activate" 2>/dev/null || source "$ROOT/.venv/bin/activate" 2>/dev/null || true
sudo -v
export NETFORGE_LIVE_TESTS=1
python -m pytest -q -vv "$@"
