from __future__ import annotations

import sqlite3


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def migrate(conn: sqlite3.Connection) -> None:
    for definition in (
        "suite_name TEXT NOT NULL DEFAULT 'live'",
        "triggered_by TEXT NOT NULL DEFAULT 'system'",
        "environment TEXT NOT NULL DEFAULT 'tier1'",
        "notes TEXT NOT NULL DEFAULT ''",
        "phase TEXT NOT NULL DEFAULT 'QUEUED'",
        "total_tests INTEGER NOT NULL DEFAULT 0",
        "passed INTEGER NOT NULL DEFAULT 0",
        "failed INTEGER NOT NULL DEFAULT 0",
        "blocked INTEGER NOT NULL DEFAULT 0",
        "skipped INTEGER NOT NULL DEFAULT 0",
        "errors INTEGER NOT NULL DEFAULT 0",
        "topology_hash TEXT",
        "topology_snapshot TEXT",
        "command TEXT",
        "worker_id TEXT",
        "cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1))",
    ):
        _add_column(conn, "executions", definition)

    for definition in (
        "test_file TEXT",
        "failure_phase TEXT",
        "duration_ms REAL",
        "stdout_path TEXT",
        "stderr_path TEXT",
    ):
        _add_column(conn, "test_results", definition)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS execution_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id INTEGER NOT NULL,
            test_result_id INTEGER,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL,
            metric_unit TEXT NOT NULL DEFAULT '',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE,
            FOREIGN KEY(test_result_id) REFERENCES test_results(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS execution_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'operator' CHECK(role IN ('admin','operator','viewer')),
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS baseline_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            baseline_id INTEGER NOT NULL,
            metric_name TEXT NOT NULL,
            baseline_value REAL NOT NULL,
            std_deviation REAL NOT NULL DEFAULT 0,
            sample_count INTEGER NOT NULL DEFAULT 0,
            window_size INTEGER NOT NULL DEFAULT 10,
            threshold_percent REAL NOT NULL DEFAULT 10.0,
            direction TEXT NOT NULL DEFAULT 'lower_is_bad' CHECK(direction IN ('lower_is_bad','higher_is_bad','two_sided')),
            computed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(baseline_id, metric_name),
            FOREIGN KEY(baseline_id) REFERENCES baselines(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS regression_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            regression_id INTEGER NOT NULL,
            metric_name TEXT NOT NULL,
            baseline_value REAL NOT NULL,
            current_value REAL NOT NULL,
            delta_percent REAL NOT NULL,
            threshold_percent REAL NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(regression_id) REFERENCES regressions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_execution_metrics_execution ON execution_metrics(execution_id);
        CREATE INDEX IF NOT EXISTS idx_execution_metrics_name ON execution_metrics(metric_name);
        CREATE INDEX IF NOT EXISTS idx_execution_events_execution ON execution_events(execution_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_test_results_execution_name ON test_results(execution_id, test_name);
        CREATE INDEX IF NOT EXISTS idx_executions_created_at ON executions(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_executions_fw ON executions(firmware_version);
        """
    )
    conn.commit()
