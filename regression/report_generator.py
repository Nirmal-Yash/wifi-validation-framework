"""Generate HTML diff reports for regression analysis."""

from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parent.parent / "results" / "reports"

CLASSIFICATION_COLORS = {
    "REGRESSION": "#c62828",
    "FIXED": "#2e7d32",
    "NEW_FAILURE": "#e65100",
    "NEW_PASS": "#1565c0",
    "UNCHANGED": "#616161",
}


def generate_diff_report(deltas, output_file="diff_report.html", firmware_version="v2.0"):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / output_file

    regressions = [d for d in deltas if d["classification"] == "REGRESSION"]
    rows = ""
    for d in deltas:
        color = CLASSIFICATION_COLORS.get(d["classification"], "#333")
        rows += f"""
        <tr>
            <td>{d['test_name']}</td>
            <td>{d['baseline']}</td>
            <td>{d['current']}</td>
            <td style="color:{color}; font-weight:bold;">{d['classification']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Regression Diff Report — {firmware_version}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 2em; }}
        h1 {{ color: #1a3c6e; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 1em; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #1a3c6e; color: white; }}
        tr:nth-child(even) {{ background: #f5f5f5; }}
        .summary {{ background: #fff3e0; padding: 1em; border-radius: 4px; }}
    </style>
</head>
<body>
    <h1>Firmware Regression Diff Report</h1>
    <p>Firmware version: <strong>{firmware_version}</strong></p>
    <div class="summary">
        <strong>{len(regressions)} regression(s) detected</strong>
        (pass &rarr; fail transitions)
    </div>
    <table>
        <tr>
            <th>Test</th>
            <th>Baseline</th>
            <th>Current</th>
            <th>Classification</th>
        </tr>
        {rows}
    </table>
</body>
</html>"""

    out.write_text(html, encoding="utf-8")
    return str(out)
