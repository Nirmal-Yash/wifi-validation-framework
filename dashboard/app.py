import io
import os
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from flask import Flask, Response, jsonify, render_template, send_file

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.db_helper import get_all_results, get_latest_results, get_metric_history, get_pass_rate_by_firmware, init_db
from dashboard.api_v1 import create_api_blueprint
from dashboard.query import DashboardQueryService
from lib.repositories import SQLiteDatabase

ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(os.getenv("NETREGRESS_DATABASE_PATH", ROOT / "results" / "test_results.db"))


def render_svg_chart(pass_rates):
    width, height = 700, 320
    if not pass_rates:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="700" height="320">'
            '<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#64748b">No test data available</text></svg>'
        )
    bars = []
    margin_left, margin_bottom, margin_top = 60, 50, 40
    chart_w = width - margin_left - 40
    chart_h = height - margin_top - margin_bottom
    bar_width = min(60, chart_w // max(1, len(pass_rates) * 2))
    spacing = chart_w / max(1, len(pass_rates))
    y_95 = margin_top + chart_h * 0.05
    grid = (
        f'<line x1="{margin_left}" y1="{y_95}" x2="{width-40}" y2="{y_95}" stroke="#94a3b8" stroke-dasharray="4,4"/>'
        f'<text x="{width-35}" y="{y_95+4}" font-family="sans-serif" font-size="11" fill="#64748b">95%</text>'
    )
    for index, row in enumerate(pass_rates):
        rate = round(100 * row["passed"] / row["total"], 1) if row["total"] else 0
        h = chart_h * rate / 100
        x = margin_left + index * spacing + (spacing - bar_width) / 2
        y = margin_top + chart_h - h
        color = "#15803d" if rate >= 95 else "#d97706" if rate >= 80 else "#b91c1c"
        bars.append(f'<rect x="{x}" y="{y}" width="{bar_width}" height="{h}" rx="4" fill="{color}"/>')
        bars.append(f'<text x="{x+bar_width/2}" y="{y-8}" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="bold" fill="#1e293b">{rate}%</text>')
        bars.append(f'<text x="{x+bar_width/2}" y="{margin_top+chart_h+24}" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#475569">{row["firmware_version"]}</text>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f'<rect width="100%" height="100%" fill="#ffffff" rx="8"/>'
        f'<text x="{width/2}" y="24" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="bold" fill="#0f172a">Test Pass Rate by Firmware Version</text>'
        f'{grid}<line x1="{margin_left}" y1="{margin_top+chart_h}" x2="{width-40}" y2="{margin_top+chart_h}" stroke="#cbd5e1"/>'
        f'{"".join(bars)}</svg>'
    )


def create_app(database_path: str | Path = DATABASE_PATH):
    flask_app = Flask(__name__)
    query = DashboardQueryService(SQLiteDatabase(database_path))
    flask_app.config["NETREGRESS_QUERY"] = query
    flask_app.register_blueprint(create_api_blueprint(query))

    @flask_app.route("/")
    def index():
        init_db()
        return render_template("index.html", results=get_latest_results(), pass_rates=get_pass_rate_by_firmware())

    @flask_app.route("/chart")
    def chart():
        init_db()
        pass_rates = get_pass_rate_by_firmware()
        if not pass_rates:
            return Response("No data", mimetype="text/plain")
        if MATPLOTLIB_AVAILABLE:
            try:
                labels = [row["firmware_version"] for row in pass_rates]
                rates = [round(100 * row["passed"] / row["total"], 1) if row["total"] else 0 for row in pass_rates]
                fig, ax = plt.subplots(figsize=(8, 4))
                colors = ["#2e7d32" if rate >= 95 else "#e65100" if rate >= 80 else "#c62828" for rate in rates]
                ax.bar(labels, rates, color=colors, edgecolor="white", width=0.5)
                ax.set_ylim(0, 110)
                ax.set_ylabel("Pass Rate (%)")
                ax.set_title("Test Pass Rate by Firmware Version")
                ax.axhline(y=95, color="#1a3c6e", linestyle="--", linewidth=1)
                for i, value in enumerate(rates):
                    ax.text(i, value + 1, f"{value}%", ha="center", fontweight="bold")
                buf = io.BytesIO()
                plt.tight_layout()
                plt.savefig(buf, format="png", dpi=120)
                plt.close(fig)
                buf.seek(0)
                return send_file(buf, mimetype="image/png")
            except Exception:
                pass
        return Response(render_svg_chart(pass_rates), mimetype="image/svg+xml")

    @flask_app.route("/regressions")
    def regressions():
        return render_template("regressions.html")

    @flask_app.route("/runs")
    def runs_page():
        return render_template("runs.html")

    @flask_app.route("/runs/<run_id>")
    def run_page(run_id):
        return render_template("run_detail.html", run_id=run_id)

    @flask_app.route("/runs/<run_id>/tests/<test_result_id>")
    def test_page(run_id, test_result_id):
        return render_template("test_detail.html", run_id=run_id, test_result_id=test_result_id)

    @flask_app.route("/performance")
    def performance_page():
        return render_template("performance.html")

    @flask_app.route("/telemetry")
    def telemetry_page():
        return render_template("telemetry.html")

    @flask_app.route("/lab-health")
    def lab_health_page():
        return render_template("lab_health.html")

    @flask_app.route("/artifacts")
    def artifacts_page():
        return render_template("artifacts.html")

    @flask_app.route("/api/results")
    def api_results():
        init_db()
        return jsonify([dict(row) for row in get_latest_results()])

    @flask_app.route("/api/pass-rates")
    def api_pass_rates():
        init_db()
        return jsonify([dict(row) for row in get_pass_rate_by_firmware()])

    @flask_app.route("/api/regressions")
    def api_regressions():
        init_db()
        from regression.diff_engine import run_diff
        return jsonify(run_diff())

    @flask_app.route("/api/metrics/<path:test_name>")
    def api_metrics(test_name):
        init_db()
        return jsonify([dict(row) for row in get_metric_history(test_name)])

    @flask_app.route("/export/csv")
    def export_csv():
        init_db()
        rows = get_all_results()
        lines = ["test_name,status,firmware_version,duration_ms,metric_value,metric_unit,timestamp,error_message"]
        for row in rows:
            error = (row["error_message"] or "").replace(",", ";").replace("\n", " ")
            lines.append(
                f"{row['test_name']},{row['status']},{row['firmware_version']},{row['duration_ms']},"
                f"{row['metric_value']},{row['metric_unit']},{row['timestamp']},{error}"
            )
        return Response(
            "\n".join(lines),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=wifi_validation_results.csv"},
        )

    return flask_app


app = create_app()

if __name__ == "__main__":
    init_db()
    print("WiFi Validation Dashboard running at http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
