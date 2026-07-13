#!/bin/bash
set -e

echo "=== WiFi Validation Framework ==="
cd "$(dirname "$0")"

if [ ! -d "wifi-venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv wifi-venv
fi

echo "Activating environment..."
source wifi-venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt

mkdir -p results/reports results/captures

FIRMWARE="${FIRMWARE_VERSION:-v1.0}"
echo "Running full test suite (firmware: $FIRMWARE)..."
pytest tests/ -v --firmware-version="$FIRMWARE" \
    --html=results/reports/report.html --self-contained-html

echo ""
echo "Test report: results/reports/report.html"
echo ""
echo "To save baseline:  python regression/baseline_runner.py --version $FIRMWARE"
echo "To simulate bug:   python regression/fw_simulator.py --version v2.0 --bug dns"
echo "To run diff:       python regression/diff_engine.py --version $FIRMWARE"
echo ""
echo "Starting dashboard at http://localhost:5000 ..."
python3 dashboard/app.py &

echo "Done."
