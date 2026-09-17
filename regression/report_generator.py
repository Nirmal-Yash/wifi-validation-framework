"""Generate comprehensive HTML diff reports for regression analysis."""

from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parent.parent / "results" / "reports"

CLASSIFICATION_COLORS = {
    "REGRESSION": "#c62828",
    "SOFT_REGRESSION": "#e65100",
    "FIXED": "#2e7d32",
    "IMPROVED": "#00897b",
    "NEW_FAILURE": "#d84315",
    "NEW_PASS": "#1565c0",
    "UNCHANGED": "#546e7a",
}


def generate_diff_report(deltas, output_file="diff_report.html", baseline_version="v1.0"):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / output_file

    regressions = [d for d in deltas if d["classification"] == "REGRESSION"]
    soft_regressions = [d for d in deltas if d["classification"] == "SOFT_REGRESSION"]
    fixed = [d for d in deltas if d["classification"] == "FIXED"]

    rows = ""
    for d in deltas:
        color = CLASSIFICATION_COLORS.get(d["classification"], "#333")

        base_metric_str = (
            f"{d['baseline_metric']} {d['metric_unit']}".strip() if d.get("baseline_metric") is not None else "—"
        )
        curr_metric_str = (
            f"{d['current_metric']} {d['metric_unit']}".strip() if d.get("current_metric") is not None else "—"
        )

        delta_str = "—"
        if d.get("delta_pct") is not None:
            sign = "+" if d["delta_pct"] > 0 else ""
            delta_str = f"{sign}{d['delta_pct']}%"

        rows += f"""
        <tr>
            <td><code>{d['test_name']}</code></td>
            <td>{d['baseline']}</td>
            <td>{d['current']}</td>
            <td>{base_metric_str}</td>
            <td>{curr_metric_str}</td>
            <td>{delta_str}</td>
            <td><span style="color:white; background:{color}; padding:3px 8px; border-radius:4px; font-weight:bold; font-size:0.85em;">{d['classification']}</span></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Regression Diff Report — Baseline {baseline_version}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 2em; background: #f8fafc; color: #1e293b; }}
        header {{ margin-bottom: 2em; }}
        h1 {{ color: #0f172a; margin-bottom: 0.2em; }}
        .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 0.85em; font-weight: 600; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1em; margin: 1.5em 0; }}
        .card {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1.2em; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
        .card-num {{ font-size: 2em; font-weight: bold; margin-top: 0.2em; }}
        table {{ border-collapse: collapse; width: 100%; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
        th {{ background: #1e293b; color: white; font-weight: 600; font-size: 0.9em; text-transform: uppercase; letter-spacing: 0.05em; }}
        tr:hover {{ background: #f1f5f9; }}
        code {{ font-size: 0.9em; background: #f1f5f9; padding: 2px 4px; border-radius: 4px; }}
    </style>
</head>
<body>
    <header>
        <h1>Firmware Regression Diff Report</h1>
        <p>Comparison against golden baseline: <strong>{baseline_version}</strong></p>
    </header>

    <div class="summary-grid">
        <div class="card" style="border-left: 4px solid #c62828;">
            <div>Hard Regressions</div>
            <div class="card-num" style="color: #c62828;">{len(regressions)}</div>
        </div>
        <div class="card" style="border-left: 4px solid #e65100;">
            <div>Soft Regressions (>20% Drop)</div>
            <div class="card-num" style="color: #e65100;">{len(soft_regressions)}</div>
        </div>
        <div class="card" style="border-left: 4px solid #2e7d32;">
            <div>Fixed / Recovered</div>
            <div class="card-num" style="color: #2e7d32;">{len(fixed)}</div>
        </div>
        <div class="card" style="border-left: 4px solid #0f172a;">
            <div>Total Compared</div>
            <div class="card-num">{len(deltas)}</div>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>Test Case</th>
                <th>Base Status</th>
                <th>Curr Status</th>
                <th>Base Metric</th>
                <th>Curr Metric</th>
                <th>Delta %</th>
                <th>Classification</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
</body>
</html>"""

    out.write_text(html, encoding="utf-8")
    return str(out)
