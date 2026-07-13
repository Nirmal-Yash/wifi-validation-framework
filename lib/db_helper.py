import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "results" / "test_results.db"


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS baselines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT NOT NULL,
                status TEXT NOT NULL,
                firmware_version TEXT,
                snapshot_time TEXT NOT NULL
            );
            """
        )


def insert_result(test_name, status, firmware_version="v1.0",
                  duration_ms=None, error_message=None, pcap_path=None):
    init_db()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO test_runs
               (test_name, status, firmware_version, duration_ms,
                error_message, pcap_path, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                test_name,
                status,
                firmware_version,
                duration_ms,
                error_message,
                pcap_path,
                datetime.utcnow().isoformat(),
            ),
        )


def save_baseline(firmware_version="v1.0"):
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM baselines WHERE firmware_version = ?", (firmware_version,))
        rows = conn.execute(
            """SELECT test_name, status FROM test_runs
               WHERE firmware_version = ?
               AND timestamp = (
                   SELECT MAX(timestamp) FROM test_runs r2
                   WHERE r2.test_name = test_runs.test_name
                   AND r2.firmware_version = ?
               )""",
            (firmware_version, firmware_version),
        ).fetchall()
        now = datetime.utcnow().isoformat()
        for row in rows:
            conn.execute(
                """INSERT INTO baselines (test_name, status, firmware_version, snapshot_time)
                   VALUES (?, ?, ?, ?)""",
                (row["test_name"], row["status"], firmware_version, now),
            )
        return len(rows)


def save_baseline_from_latest_passes(firmware_version="v1.0"):
    """Save the most recent result per test as baseline."""
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM baselines WHERE firmware_version = ?", (firmware_version,))
        rows = conn.execute(
            """SELECT test_name, status FROM test_runs t1
               WHERE timestamp = (
                   SELECT MAX(timestamp) FROM test_runs t2
                   WHERE t2.test_name = t1.test_name
               )"""
        ).fetchall()
        now = datetime.utcnow().isoformat()
        for row in rows:
            conn.execute(
                """INSERT INTO baselines (test_name, status, firmware_version, snapshot_time)
                   VALUES (?, ?, ?, ?)""",
                (row["test_name"], row["status"], firmware_version, now),
            )
        return len(rows)


def get_latest_results():
    init_db()
    with _connect() as conn:
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


def get_all_results():
    init_db()
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM test_runs ORDER BY timestamp DESC"
        ).fetchall()
