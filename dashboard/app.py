import io
import sys
from pathlib import Path

# Matplotlib is optional: fallback to lightweight, zero-dependency SVG chart if not installed
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from flask import Flask, Response, jsonify, render_template, send_file

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.db_helper import (
    get_all_results,
    get_latest_results,
    get_metric_history,
    get_pass_rate_by_firmware,
    init_db,
)
from regression.diff_engine import run_diff
from regression.regression_classifier import REGRESSION, SOFT_REGRESSION

app = Flask(__name__)
ROOT = Path(__file__).resolve().parent.parent


def render_svg_chart(pass_rates):
    """Pure-Python, zero-dependency SVG bar chart generator."""
    width, height = 700, 320
    if not pass_rates:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" '
            f'font-family="sans-serif" font-size="16" fill="#64748b">No test data available</text></svg>'
        )

    bars = []
    n = len(pass_rates)
    margin_left = 60
    margin_bottom = 50
    margin_top = 40
    chart_w = width - margin_left - 40
    chart_h = height - margin_top - margin_bottom
    bar_width = min(60, chart_w // max(1, n * 2))
    spacing = chart_w / max(1, n)

    y_95 = margin_top + chart_h * (1 - 95 / 100)
    grid = (
        f'<line x1="{margin_left}" y1="{y_95}" x2="{width - 40}" y2="{y_95}" '
        f'stroke="#94a3b8" stroke-dasharray="4,4" stroke-width="1"/>'
        f'<text x="{width - 35}" y="{y_95 + 4}" font-family="sans-serif" font-size="11" fill="#64748b">95%</text>'
    )

    for i, r in enumerate(pass_rates):
        v_name = r["firmware_version"]
        rate = round(100 * r["passed"] / r["total"], 1) if r["total"] else 0
        h = chart_h * (rate / 100)
        x = margin_left + i * spacing + (spacing - bar_width) / 2
        y = margin_top + (chart_h - h)
        color = "#15803d" if rate >= 95 else ("#d97706" if rate >= 80 else "#b91c1c")

        bars.append(f'<rect x="{x}" y="{y}" width="{bar_width}" height="{h}" rx="4" fill="{color}"/>')
        bars.append(
            f'<text x="{x + bar_width/2}" y="{y - 8}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="12" font-weight="bold" fill="#1e293b">{rate}%</text>'
        )
        bars.append(
            f'<text x="{x + bar_width/2}" y="{margin_top + chart_h + 24}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="12" fill="#475569">{v_name}</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
        <rect width="100%" height="100%" fill="#ffffff" rx="8"/>
        <text x="{width/2}" y="24" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="bold" fill="#0f172a">Test Pass Rate by Firmware Version</text>
        {grid}
        <line x1="{margin_left}" y1="{margin_top + chart_h}" x2="{width - 40}" y2="{margin_top + chart_h}" stroke="#cbd5e1" stroke-width="1.5"/>
        {''.join(bars)}
    </svg>"""
    return svg


@app.route("/")
def index():
    init_db()
    results = get_latest_results()
    pass_rates = get_pass_rate_by_firmware()
    return render_template("index.html", results=results, pass_rates=pass_rates)


@app.route("/chart")
def chart():
    init_db()
    pass_rates = get_pass_rate_by_firmware()
    if not pass_rates:
        return Response("No data", mimetype="text/plain")

    # If matplotlib is available, render PNG; otherwise render vector SVG instantly with 0 memory
    if MATPLOTLIB_AVAILABLE:
        try:
            labels = [r["firmware_version"] for r in pass_rates]
            rates = [
                round(100 * r["passed"] / r["total"], 1) if r["total"] else 0
                for r in pass_rates
            ]

            fig, ax = plt.subplots(figsize=(8, 4))
            colors = ["#2e7d32" if r >= 95 else "#e65100" if r >= 80 else "#c62828" for r in rates]
            ax.bar(labels, rates, color=colors, edgecolor="white", width=0.5)
            ax.set_ylim(0, 110)
            ax.set_ylabel("Pass Rate (%)")
            ax.set_title("Test Pass Rate by Firmware Version")
            ax.axhline(y=95, color="#1a3c6e", linestyle="--", linewidth=1)
            for i, v in enumerate(rates):
                ax.text(i, v + 1, f"{v}%", ha="center", fontweight="bold")

            buf = io.BytesIO()
            plt.tight_layout()
            plt.savefig(buf, format="png", dpi=120)
            plt.close()
            buf.seek(0)
            return send_file(buf, mimetype="image/png")
        except Exception:
            pass

    svg_content = render_svg_chart(pass_rates)
    return Response(svg_content, mimetype="image/svg+xml")


@app.route("/regressions")
def regressions():
    init_db()
    deltas = run_diff()
    hard_regressions = [d for d in deltas if d["classification"] == REGRESSION]
    soft_regressions = [d for d in deltas if d["classification"] == SOFT_REGRESSION]
    return render_template(
        "regressions.html",
        regressions=hard_regressions,
        soft_regressions=soft_regressions,
        all_deltas=deltas,
    )


# ─── RESTful JSON API Endpoints ─────────────────────────────────────────────


@app.route("/api/results")
def api_results():
    """Real-time JSON feed of latest test results with metrics."""
    init_db()
    results = get_latest_results()
    return jsonify([dict(r) for r in results])


@app.route("/api/pass-rates")
def api_pass_rates():
    init_db()
    pass_rates = get_pass_rate_by_firmware()
    return jsonify([dict(r) for r in pass_rates])


@app.route("/api/regressions")
def api_regressions():
    init_db()
    deltas = run_diff()
    return jsonify(deltas)


@app.route("/api/metrics/<path:test_name>")
def api_metrics(test_name):
    """Return historical metric timeline for a given test across firmware versions."""
    init_db()
    rows = get_metric_history(test_name)
    return jsonify([dict(r) for r in rows])


@app.route("/export/csv")
def export_csv():
    init_db()
    results = get_all_results()
    lines = ["test_name,status,firmware_version,duration_ms,metric_value,metric_unit,timestamp,error_message"]
    for r in results:
        err = (r["error_message"] or "").replace(",", ";").replace("\n", " ")
        lines.append(
            f"{r['test_name']},{r['status']},{r['firmware_version']},"
            f"{r['duration_ms']},{r['metric_value']},{r['metric_unit']},{r['timestamp']},{err}"
        )
    return Response(
        "\n".join(lines),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=wifi_validation_results.csv"},
    )


if __name__ == "__main__":
    init_db()
    print("WiFi Validation Dashboard running at http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
