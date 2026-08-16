from __future__ import annotations

import math
import statistics
from typing import Any

from engine.execution_store import connect

DEFAULT_WINDOW = 10
DEFAULT_THRESHOLD_PERCENT = 10.0
MIN_SAMPLES = 5


def compute_baseline(metric_name: str, topology_version_id: int | None = None, window: int = DEFAULT_WINDOW, exclude_execution_id: int | None = None) -> dict[str, Any] | None:
    window = max(2, min(int(window), 100))
    with connect() as conn:
        params: list[Any] = [metric_name]
        sql = """SELECT em.metric_value, e.id execution_id
                 FROM execution_metrics em
                 JOIN executions e ON e.id=em.execution_id
                 WHERE em.metric_name=? AND e.status='PASSED'"""
        if topology_version_id is not None:
            sql += " AND e.topology_version_id=?"
            params.append(topology_version_id)
        if exclude_execution_id is not None:
            sql += " AND e.id<>?"
            params.append(exclude_execution_id)
        sql += " ORDER BY e.id DESC LIMIT ?"
        params.append(window)
        rows = conn.execute(sql, params).fetchall()
    values = [float(row["metric_value"]) for row in rows]
    if not values:
        return None
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return {"metric_name": metric_name, "baseline_value": mean, "std_deviation": std, "sample_count": len(values), "window_size": window}


def compare_value(current: float, baseline: float, threshold_percent: float = DEFAULT_THRESHOLD_PERCENT, direction: str = "lower_is_bad") -> dict[str, Any]:
    if baseline == 0:
        delta = 0.0 if current == 0 else math.inf
    else:
        delta = ((current - baseline) / abs(baseline)) * 100.0
    if direction == "lower_is_bad":
        regression = delta < -abs(threshold_percent)
    elif direction == "higher_is_bad":
        regression = delta > abs(threshold_percent)
    else:
        regression = abs(delta) > abs(threshold_percent)
    return {"current_value": current, "baseline_value": baseline, "delta_percent": delta, "regression": regression, "threshold_percent": threshold_percent}


def analyze_execution(execution_id: int, threshold_percent: float = DEFAULT_THRESHOLD_PERCENT) -> list[dict[str, Any]]:
    """Compare candidate metrics against prior successful executions only."""
    with connect() as conn:
        current = conn.execute(
            "SELECT em.metric_name, em.metric_value, e.topology_version_id FROM execution_metrics em JOIN executions e ON e.id=em.execution_id WHERE e.id=?",
            (execution_id,),
        ).fetchall()
    regressions: list[dict[str, Any]] = []
    for row in current:
        baseline = compute_baseline(row["metric_name"], row["topology_version_id"], exclude_execution_id=execution_id)
        if not baseline or baseline["sample_count"] < MIN_SAMPLES:
            continue
        comparison = compare_value(float(row["metric_value"]), baseline["baseline_value"], threshold_percent)
        if not comparison["regression"]:
            continue
        severity = "CRITICAL" if abs(comparison["delta_percent"]) >= threshold_percent * 2 else "HIGH"
        with connect() as conn:
            conn.execute("INSERT OR IGNORE INTO firmware_metadata(firmware_version) VALUES ('rolling')")
            conn.execute("INSERT OR IGNORE INTO baselines(name,firmware_version,topology_version_id) VALUES(?,?,?)", (f"auto:{row['metric_name']}", "rolling", None))
            baseline_row = conn.execute("SELECT id FROM baselines WHERE name=? AND firmware_version='rolling'", (f"auto:{row['metric_name']}",)).fetchone()
            conn.execute(
                "INSERT INTO baseline_metrics(baseline_id,metric_name,baseline_value,std_deviation,sample_count,window_size,threshold_percent) VALUES(?,?,?,?,?,?,?) ON CONFLICT(baseline_id,metric_name) DO UPDATE SET baseline_value=excluded.baseline_value,std_deviation=excluded.std_deviation,sample_count=excluded.sample_count,window_size=excluded.window_size,threshold_percent=excluded.threshold_percent,computed_at=CURRENT_TIMESTAMP",
                (baseline_row["id"], row["metric_name"], baseline["baseline_value"], baseline["std_deviation"], baseline["sample_count"], baseline["window_size"], threshold_percent),
            )
            cur = conn.execute("INSERT INTO regressions(baseline_id,execution_id,test_name,baseline_status,candidate_status,severity) VALUES(?,?,?,?,?,?)", (baseline_row["id"], execution_id, "metric", "BASELINE", "REGRESSION", severity))
            regression_id = cur.lastrowid
            conn.execute("INSERT INTO regression_metrics(regression_id,metric_name,baseline_value,current_value,delta_percent,threshold_percent) VALUES(?,?,?,?,?,?)", (regression_id, row["metric_name"], baseline["baseline_value"], comparison["current_value"], comparison["delta_percent"], threshold_percent))
            conn.commit()
        regressions.append({"regression_id": regression_id, **comparison, "metric_name": row["metric_name"], "severity": severity})
    return regressions
