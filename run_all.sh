#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${NETREGRESS_VENV_DIR:-$ROOT_DIR/wifi-venv}"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python scripts/netregress_install.py

FIRMWARE="${FIRMWARE_VERSION:-v1.0}"
python -m pytest tests/ -v --firmware-version="$FIRMWARE" \
  --html=results/reports/report.html --self-contained-html

echo "Test report: results/reports/report.html"
echo "Baseline promotion remains explicit: python regression/baseline_runner.py --version $FIRMWARE"

# Preserve the historical default of starting the dashboard after validation,
# but route through the authenticated Runner launcher instead of dashboard/app.py.
if [[ "${RUN_DASHBOARD:-1}" == "1" ]]; then
  exec "$ROOT_DIR/scripts/start_dashboard.sh"
fi
