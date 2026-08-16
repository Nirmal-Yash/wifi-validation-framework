from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db.init_db import DB_PATH, initialize
from db.migrations import migrate

ROOT = Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    initialize(DB_PATH)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    migrate(conn)
    return conn


def topology_snapshot() -> tuple[str | None, int | None, str | None]:
    path = ROOT / "config" / "devices.yaml"
    if not path.exists():
        return None, None, None
    content = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with connect() as conn:
        row = conn.execute(
            "SELECT tv.id, tv.version FROM topology_versions tv "
            "JOIN topologies t ON t.id=tv.topology_id "
            "WHERE tv.status='ACTIVE' ORDER BY tv.id DESC LIMIT 1"
        ).fetchone()
    return digest, (row["id"] if row else None), content


def ensure_firmware(conn: sqlite3.Connection, version: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO firmware_metadata(firmware_version) VALUES (?)",
        (version,),
    )


def create_execution(
    firmware_version: str = "1.0.0",
    suite_name: str = "live",
    triggered_by: str = "api",
    environment: str = "tier1",
    notes: str = "",
    command: str = "",
) -> int:
    topology_hash, topology_version_id, snapshot = topology_snapshot()
    with connect() as conn:
        ensure_firmware(conn, firmware_version)
        cur = conn.execute(
            """INSERT INTO executions
            (firmware_version, topology_version_id, mode, status, suite_name,
             triggered_by, environment, notes, topology_hash, topology_snapshot,
             command)
            VALUES (?, ?, ?, 'QUEUED', ?, ?, ?, ?, ?, ?, ?)""",
            (
                firmware_version,
                topology_version_id,
                environment,
                suite_name,
                triggered_by,
                environment,
                notes,
                topology_hash,
                snapshot,
                command,
            ),
        )
        execution_id = int(cur.lastrowid)
        add_event(conn, execution_id, "QUEUED", "Execution queued")
        conn.commit()
    return execution_id


def add_event(conn: sqlite3.Connection, execution_id: int, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO execution_events(execution_id,event_type,message,payload_json) VALUES(?,?,?,?)",
        (execution_id, event_type, message, json.dumps(payload or {}, sort_keys=True)),
    )


def set_status(execution_id: int, status: str, message: str | None = None, **fields: Any) -> None:
    allowed = {"QUEUED", "PROVISIONING", "RUNNING", "COLLECTING", "ANALYZING", "PASSED", "FAILED", "ERROR", "CANCELLED"}
    if status not in allowed:
        raise ValueError(f"Unsupported execution status: {status}")
    assignments = ["status=?"]
    values: list[Any] = [status]
    if status in {"RUNNING", "PROVISIONING"}:
        assignments.append("started_at=COALESCE(started_at, CURRENT_TIMESTAMP)")
    if status in {"PASSED", "FAILED", "ERROR", "CANCELLED"}:
        assignments.append("finished_at=CURRENT_TIMESTAMP")
    for key in ("worker_id", "command", "notes", "total_tests", "passed", "failed", "blocked", "skipped", "errors"):
        if key in fields:
            assignments.append(f"{key}=?")
            values.append(fields[key])
    values.append(execution_id)
    with connect() as conn:
        conn.execute(f"UPDATE executions SET {', '.join(assignments)} WHERE id=?", values)
        add_event(conn, execution_id, status, message or f"Execution status changed to {status}", fields)
        conn.commit()


def mark_cancel_requested(execution_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE executions SET cancel_requested=1 WHERE id=? AND status IN ('QUEUED','PROVISIONING','RUNNING','COLLECTING','ANALYZING')",
            (execution_id,),
        )
        conn.commit()
        return cur.rowcount == 1


def is_cancel_requested(execution_id: int) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT cancel_requested FROM executions WHERE id=?", (execution_id,)).fetchone()
    return bool(row and row["cancel_requested"])


def get_execution(execution_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM executions WHERE id=?", (execution_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["results"] = [dict(r) for r in conn.execute("SELECT * FROM test_results WHERE execution_id=? ORDER BY id", (execution_id,))]
        result["metrics"] = [dict(r) for r in conn.execute("SELECT * FROM execution_metrics WHERE execution_id=? ORDER BY id", (execution_id,))]
        result["events"] = [dict(r) for r in conn.execute("SELECT * FROM execution_events WHERE execution_id=? ORDER BY id", (execution_id,))]
        return result


def list_executions(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with connect() as conn:
        if status:
            rows = conn.execute("SELECT * FROM executions WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM executions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def record_test_results(execution_id: int, junit_path: Path) -> dict[str, int]:
    import xml.etree.ElementTree as ET

    if not junit_path.exists():
        return {"total": 0, "passed": 0, "failed": 0, "blocked": 0, "skipped": 0, "errors": 0}
    root = ET.parse(junit_path).getroot()
    cases = root.findall(".//testcase")
    counts = {"total": 0, "passed": 0, "failed": 0, "blocked": 0, "skipped": 0, "errors": 0}
    with connect() as conn:
        conn.execute("DELETE FROM test_results WHERE execution_id=?", (execution_id,))
        for case in cases:
            counts["total"] += 1
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            if failure is not None:
                status, bucket = "FAILED", "failed"
                message = failure.get("message") or (failure.text or "")
            elif error is not None:
                status, bucket = "ERROR", "errors"
                message = error.get("message") or (error.text or "")
            elif skipped is not None:
                status, bucket = "SKIPPED", "skipped"
                message = skipped.get("message") or ""
            else:
                status, bucket, message = "PASSED", "passed", ""
            counts[bucket] += 1
            classname = case.get("classname") or ""
            name = case.get("name") or "unknown"
            duration = float(case.get("time") or 0.0)
            conn.execute(
                """INSERT INTO test_results
                (execution_id,test_name,test_file,status,duration,duration_ms,error_message,failure_phase)
                VALUES(?,?,?,?,?,?,?,?)""",
                (execution_id, name, classname, status, duration, duration * 1000.0, message, ""),
            )
        conn.execute(
            """UPDATE executions SET total_tests=?,passed=?,failed=?,blocked=?,skipped=?,errors=? WHERE id=?""",
            (counts["total"], counts["passed"], counts["failed"], counts["blocked"], counts["skipped"], counts["errors"], execution_id),
        )
        conn.commit()
    return counts
