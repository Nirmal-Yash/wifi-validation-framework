import io
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import Flask, Response, render_template, send_file

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.db_helper import get_all_results, get_latest_results, get_pass_rate_by_firmware, init_db
from regression.diff_engine import run_diff
from regression.regression_classifier import REGRESSION

app = Flask(__name__)
ROOT = Path(__file__).resolve().parent.parent


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

    labels = [r["firmware_version"] for r in pass_rates]
    rates = [
        round(100 * r["passed"] / r["total"], 1) if r["total"] else 0
        for r in pass_rates
    ]

    fig, ax = plt.subplots(figsize=(8, 4))
    colors = ["#2e7d32" if r >= 95 else "#e65100" if r >= 80 else "#c62828" for r in rates]
    ax.bar(labels, rates, color=colors, edgecolor="white")
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


@app.route("/regressions")
def regressions():
    init_db()
    deltas = run_diff()
    regression_items = [d for d in deltas if d["classification"] == REGRESSION]
    return render_template("regressions.html", regressions=regression_items, all_deltas=deltas)


@app.route("/export/csv")
def export_csv():
    init_db()
    results = get_all_results()
    lines = ["test_name,status,firmware_version,duration_ms,timestamp,error_message"]
    for r in results:
        err = (r["error_message"] or "").replace(",", ";").replace("\n", " ")
        lines.append(
            f"{r['test_name']},{r['status']},{r['firmware_version']},"
            f"{r['duration_ms']},{r['timestamp']},{err}"
        )
    return Response("\n".join(lines), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=results.csv"})


if __name__ == "__main__":
    init_db()
    print("Dashboard running at http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
