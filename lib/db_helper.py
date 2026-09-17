import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "results" / "test_results.db"


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_columns(conn):
    """Ensure newer columns (metric_value, metric_unit) exist in legacy DB files."""
    # Check test_runs columns
    cur = conn.execute("PRAGMA table_info(test_runs)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "metric_value" not in existing_cols:
        conn.execute("ALTER TABLE test_runs ADD COLUMN metric_value REAL")
    if "metric_unit" not in existing_cols:
        conn.execute("ALTER TABLE test_runs ADD COLUMN metric_unit TEXT")

    # Check baselines columns
    cur = conn.execute("PRAGMA table_info(baselines)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "metric_value" not in existing_cols:
        conn.execute("ALTER TABLE baselines ADD COLUMN metric_value REAL")
    if "metric_unit" not in existing_cols:
        conn.execute("ALTER TABLE baselines ADD COLUMN metric_unit TEXT")


def init_db():
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS test_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT NOT NULL,
                status TEXT NOT NULL,
                firmware_version TEXT,
                duration_ms INTEGER,
                error_message TEXT,
                pcap_path TEXT,
                metric_value REAL,
                metric_unit TEXT,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS baselines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT NOT NULL,
                status TEXT NOT NULL,
                firmware_version TEXT,
                metric_value REAL,
                metric_unit TEXT,
                snapshot_time TEXT NOT NULL
            );
            """
        )
        _migrate_columns(conn)


def insert_result(
    test_name,
    status,
    firmware_version="v1.0",
    duration_ms=None,
    error_message=None,
    pcap_path=None,
    metric_value=None,
    metric_unit=None,
):
    init_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO test_runs
               (test_name, status, firmware_version, duration_ms,
                error_message, pcap_path, metric_value, metric_unit, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                test_name,
                status,
                firmware_version,
                duration_ms,
                error_message,
                pcap_path,
                metric_value,
                metric_unit,
                now_iso,
            ),
        )


def save_baseline(firmware_version="v1.0"):
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM baselines WHERE firmware_version = ?", (firmware_version,))
        rows = conn.execute(
            """SELECT test_name, status, metric_value, metric_unit FROM test_runs
               WHERE firmware_version = ?
               AND timestamp = (
                   SELECT MAX(timestamp) FROM test_runs r2
                   WHERE r2.test_name = test_runs.test_name
                   AND r2.firmware_version = ?
               )""",
            (firmware_version, firmware_version),
        ).fetchall()
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            conn.execute(
                """INSERT INTO baselines
                   (test_name, status, firmware_version, metric_value, metric_unit, snapshot_time)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    row["test_name"],
                    row["status"],
                    firmware_version,
                    row["metric_value"],
                    row["metric_unit"],
                    now,
                ),
            )
        return len(rows)


def save_baseline_from_latest_passes(firmware_version="v1.0"):
    """Save the most recent result per test for the specified firmware version as baseline."""
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM baselines WHERE firmware_version = ?", (firmware_version,))
        rows = conn.execute(
            """SELECT test_name, status, metric_value, metric_unit FROM test_runs t1
               WHERE firmware_version = ?
               AND timestamp = (
                   SELECT MAX(timestamp) FROM test_runs t2
                   WHERE t2.test_name = t1.test_name
                   AND t2.firmware_version = ?
               )""",
            (firmware_version, firmware_version),
        ).fetchall()
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            conn.execute(
                """INSERT INTO baselines
                   (test_name, status, firmware_version, metric_value, metric_unit, snapshot_time)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    row["test_name"],
                    row["status"],
                    firmware_version,
                    row["metric_value"],
                    row["metric_unit"],
                    now,
                ),
            )
        return len(rows)


def get_latest_results(firmware_version=None):
    init_db()
    with _connect() as conn:
        if firmware_version:
            return conn.execute(
                """SELECT * FROM test_runs t1
                   WHERE firmware_version = ?
                     AND timestamp = (
                         SELECT MAX(timestamp) FROM test_runs t2
                         WHERE t2.test_name = t1.test_name
                           AND t2.firmware_version = ?
                     )
                   ORDER BY test_name""",
                (firmware_version, firmware_version),
            ).fetchall()
        return conn.execute(
            """SELECT * FROM test_runs t1
               WHERE timestamp = (
                   SELECT MAX(timestamp) FROM test_runs t2
                   WHERE t2.test_name = t1.test_name
               )
               ORDER BY test_name"""
        ).fetchall()


def get_baseline(firmware_version="v1.0"):
    init_db()
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM baselines WHERE firmware_version = ? ORDER BY test_name",
            (firmware_version,),
        ).fetchall()


def get_metric_history(test_name):
    """Retrieve historical metric datapoints for a given test across all runs."""
    init_db()
    with _connect() as conn:
        return conn.execute(
            """SELECT id, test_name, status, firmware_version,
                      metric_value, metric_unit, duration_ms, timestamp
               FROM test_runs
               WHERE test_name = ? AND metric_value IS NOT NULL
               ORDER BY timestamp ASC""",
            (test_name,),
        ).fetchall()


def get_pass_rate_by_firmware():
    init_db()
    with _connect() as conn:
        return conn.execute(
            """SELECT firmware_version,
                      COUNT(*) as total,
                      SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) as passed
               FROM test_runs
               GROUP BY firmware_version
               ORDER BY firmware_version"""
        ).fetchall()


def get_all_results(limit=500):
    init_db()
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM test_runs ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
