from __future__ import annotations

import os
import subprocess
import threading
import uuid
from pathlib import Path

from engine.execution_store import (
    ROOT,
    create_execution,
    is_cancel_requested,
    mark_cancel_requested,
    record_test_results,
    set_status,
)


class ExecutionOrchestrator:
    """Small single-host execution manager.

    Intentionally uses a single worker thread and subprocess isolation. This keeps
    the current Tier-1 deployment simple while establishing a stable API boundary
    that can later be backed by a worker pool or queue service.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[int, subprocess.Popen[str]] = {}
        self._thread: threading.Thread | None = None

    def submit(
        self,
        firmware_version: str = "1.0.0",
        suite_name: str = "live",
        triggered_by: str = "api",
        environment: str = "tier1",
        notes: str = "",
        pytest_args: list[str] | None = None,
    ) -> int:
        args = list(pytest_args or ["tests/", "-m", "live", "-v"])
        command = "python -m pytest " + " ".join(args)
        execution_id = create_execution(firmware_version, suite_name, triggered_by, environment, notes, command)
        thread = threading.Thread(
            target=self._run,
            args=(execution_id, firmware_version, args),
            name=f"netforge-execution-{execution_id}",
            daemon=True,
        )
        thread.start()
        with self._lock:
            self._thread = thread
        return execution_id

    def cancel(self, execution_id: int) -> bool:
        accepted = mark_cancel_requested(execution_id)
        if not accepted:
            return False
        with self._lock:
            process = self._jobs.get(execution_id)
        if process and process.poll() is None:
            process.terminate()
        return True

    def _run(self, execution_id: int, firmware_version: str, args: list[str]) -> None:
        junit_path = ROOT / "artifacts" / "reports" / f"execution-{execution_id}.xml"
        log_path = ROOT / "artifacts" / "reports" / f"execution-{execution_id}.log"
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        worker_id = f"local-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        command = ["python", "-m", "pytest", *args, f"--fw-version={firmware_version}", f"--junitxml={junit_path}"]
        try:
            set_status(execution_id, "PROVISIONING", "Preparing execution worker", worker_id=worker_id, command=" ".join(command))
            if is_cancel_requested(execution_id):
                set_status(execution_id, "CANCELLED", "Execution cancelled before start", worker_id=worker_id)
                return
            env = os.environ.copy()
            env["NETFORGE_EXECUTION_ID"] = str(execution_id)
            env["NETFORGE_LIVE_TESTS"] = env.get("NETFORGE_LIVE_TESTS", "1")
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                with self._lock:
                    self._jobs[execution_id] = process
                set_status(execution_id, "RUNNING", "Pytest worker started", worker_id=worker_id)
                return_code = process.wait()
            with self._lock:
                self._jobs.pop(execution_id, None)
            if is_cancel_requested(execution_id):
                set_status(execution_id, "CANCELLED", "Execution cancelled", worker_id=worker_id)
                return
            set_status(execution_id, "COLLECTING", "Collecting structured test results", worker_id=worker_id)
            counts = record_test_results(execution_id, junit_path)
            set_status(execution_id, "ANALYZING", "Execution results persisted", worker_id=worker_id, **counts)
            final = "PASSED" if return_code == 0 and counts["failed"] == 0 and counts["errors"] == 0 else "FAILED"
            set_status(execution_id, final, f"Execution completed with exit code {return_code}", worker_id=worker_id, **counts)
        except Exception as exc:
            with self._lock:
                self._jobs.pop(execution_id, None)
            set_status(execution_id, "ERROR", f"Execution worker error: {exc}", worker_id=worker_id, notes=str(exc))


orchestrator = ExecutionOrchestrator()
