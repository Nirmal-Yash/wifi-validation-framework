#!/bin/bash
echo "=== WiFi Validation Framework ==="
echo "Activating environment..."
source wifi-venv/bin/activate

echo "Running full test suite..."
pytest tests/ -v   --html=results/reports/report.html   --self-contained-html

echo "Starting dashboard..."
python3 dashboard/app.py &

echo "Done. Open http://localhost:5000 for dashboard"
echo "Open results/reports/report.html for test report"
