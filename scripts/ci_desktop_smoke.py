#!/usr/bin/env python3
"""Headless installed-package smoke test for the NetRegress Linux desktop app.

The test launches the actual Tauri executable inside Xvfb. It verifies that the
packaged Python sidecar becomes healthy, creates the first persistent Owner,
restarts the desktop app, and authenticates the same account from the same
private XDG data directory. It never uses a repository checkout or a system
Python interpreter to run the application backend.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OWNER_PASSWORD = secrets.token_urlsafe(32)
PORT_PATTERN = re.compile(r"https?://127\.0\.0\.1:(\d{1,5})")


class SmokeFailure(RuntimeError):
    """A packaged desktop lifecycle assertion failed."""


def _request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    cookie: str | None = None,
    origin: str | None = None,
    timeout: float = 3.0,
) -> tuple[int, dict, str | None]:
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    if origin:
        headers["Origin"] = origin
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"http://127.0.0.1:{port}/api/v1{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            data = json.loads(raw.decode("utf-8")) if raw else {}
            return response.status, data, response.headers.get("Set-Cookie")
    except HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {"raw": raw.decode("utf-8", errors="replace")[:500]}
        return exc.code, data, exc.headers.get("Set-Cookie")
    except (URLError, TimeoutError, OSError) as exc:
        raise SmokeFailure(f"local API request {method} {path} failed: {type(exc).__name__}") from exc


def _find_backend_log(data_home: Path) -> Path | None:
    candidates = list(data_home.rglob("backend.log"))
    return max(candidates, key=lambda item: item.stat().st_mtime_ns) if candidates else None


def _wait_backend(data_home: Path, process: subprocess.Popen, *, timeout: float = 55.0) -> tuple[int, Path]:
    deadline = time.monotonic() + timeout
    last_log = None
    last_port = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            details = process.stdout_path.read_text(encoding="utf-8", errors="replace")[-5000:]
            backend_log = _find_backend_log(data_home)
            backend_details = (
                backend_log.read_text(encoding="utf-8", errors="replace")[-12000:]
                if backend_log is not None and backend_log.is_file()
                else "<backend.log was not created>"
            )
            raise SmokeFailure(
                f"desktop process exited during startup ({process.returncode}); "
                f"backend log: {backend_details}; launcher output: {details}"
            )
        log_path = _find_backend_log(data_home)
        if log_path is not None:
            last_log = log_path
            content = log_path.read_text(encoding="utf-8", errors="replace")
            matches = PORT_PATTERN.findall(content)
            if matches:
                port = int(matches[-1])
                if 1024 <= port <= 65535:
                    last_port = port
                    try:
                        status, body, _ = _request(port, "/health", timeout=1.0)
                        if status == 200 and body.get("data", {}).get("status") == "ok":
                            return port, log_path
                    except SmokeFailure:
                        pass
        time.sleep(0.25)

    log_text = (
        last_log.read_text(encoding="utf-8", errors="replace")[-8000:]
        if last_log and last_log.exists() else "<backend.log was not created>"
    )
    launcher_text = process.stdout_path.read_text(encoding="utf-8", errors="replace")[-5000:]
    raise SmokeFailure(
        "packaged backend did not become healthy; "
        f"last discovered port={last_port}; backend log: {log_text}; launcher log: {launcher_text}"
    )


def _start_app(
    executable: Path,
    *,
    state_root: Path,
    label: str,
    appimage: bool,
) -> tuple[subprocess.Popen, Path]:
    home = state_root / "home"
    data_home = state_root / "data"
    config_home = state_root / "config"
    cache_home = state_root / "cache"
    state_home = state_root / "state"
    for directory in (home, data_home, config_home, cache_home, state_home):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)

    launcher_log = state_root / f"{label}-launcher.log"
    env = os.environ.copy()
    env.update({
        "HOME": str(home),
        "XDG_DATA_HOME": str(data_home),
        "XDG_CONFIG_HOME": str(config_home),
        "XDG_CACHE_HOME": str(cache_home),
        "XDG_STATE_HOME": str(state_home),
        "GDK_BACKEND": "x11",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "WEBKIT_DISABLE_COMPOSITING_MODE": "1",
        "NO_AT_BRIDGE": "1",
    })
    command = ["xvfb-run", "-a", "--server-args=-screen 0 1600x1000x24"]
    if appimage:
        env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    command.append(str(executable.resolve()))

    output = launcher_log.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=output,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
        close_fds=True,
    )
    # Keep a named handle for actionable diagnostics in _wait_backend().
    process.stdout_path = launcher_log  # type: ignore[attr-defined]
    process._smoke_output = output  # type: ignore[attr-defined]
    return process, data_home


def _stop_app(process: subprocess.Popen) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
    output = getattr(process, "_smoke_output", None)
    if output is not None:
        output.close()


def _create_owner_and_login(port: int, *, first_run: bool) -> None:
    status, body, _ = _request(port, "/setup/status")
    if status != 200:
        raise SmokeFailure(f"first-run status endpoint returned HTTP {status}: {body}")
    required = body.get("data", {}).get("first_run_required")
    if required is not (True if first_run else False):
        raise SmokeFailure(f"unexpected first-run state after restart: {required!r}")

    if first_run:
        status, body, _ = _request(
            port,
            "/setup/owner",
            method="POST",
            payload={"username": "owner", "password": OWNER_PASSWORD},
            origin="tauri://localhost",
        )
        if status != 200:
            raise SmokeFailure(f"first Owner creation returned HTTP {status}: {body}")
        if body.get("data", {}).get("global_role") != "OWNER":
            raise SmokeFailure("first-run setup did not create a Global Owner")

    status, body, set_cookie = _request(
        port,
        "/auth/login",
        method="POST",
        payload={"username": "owner", "password": OWNER_PASSWORD},
    )
    if status != 200 or not set_cookie:
        raise SmokeFailure(f"Owner login returned HTTP {status}: {body}")
    cookie = set_cookie.split(";", 1)[0]
    status, body, _ = _request(port, "/auth/me", cookie=cookie)
    profile = body.get("data", {})
    if status != 200 or profile.get("username") != "owner" or profile.get("role") != "OWNER":
        raise SmokeFailure(f"authenticated Owner profile could not be restored: HTTP {status}, {body}")


def _run_packaged_backend_checks(
    backend_executable: Path,
    *,
    state_root: Path,
    database: Path,
) -> dict:
    """Exercise the actual frozen pytest and pipeline-worker child dispatch."""
    if not backend_executable.is_file() or not os.access(backend_executable, os.X_OK):
        raise SmokeFailure(
            "the package resource backend/netregress-backend is missing or not executable"
        )
    data_home = state_root / "data"
    results_dir = database.parent
    process_dir = results_dir / "processes"
    logs_dir = data_home / "logs"
    config_dir = state_root / "config"
    for directory in (process_dir, logs_dir, config_dir):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)

    env = os.environ.copy()
    env.update({
        "HOME": str(state_root / "home"),
        "XDG_DATA_HOME": str(data_home),
        "XDG_CONFIG_HOME": str(config_dir),
        "NETREGRESS_PACKAGED": "1",
        "NETREGRESS_AUTH_REQUIRED": "1",
        "NETREGRESS_AUTH_USERS_JSON": "",
        "NETREGRESS_USER_DATA_DIR": str(data_home),
        "NETREGRESS_LOCAL_DIR": str(data_home),
        "NETREGRESS_CONFIG_DIR": str(config_dir),
        "NETREGRESS_LOG_DIR": str(logs_dir),
        "NETREGRESS_RESULTS_DIR": str(results_dir),
        "NETREGRESS_PROCESS_DIR": str(process_dir),
        "NETREGRESS_DATABASE_PATH": str(database),
        "PYTHONNOUSERSITE": "1",
        # Packaged contract tests run without real lab secrets or devices.
        "NETREGRESS_CI_MODE": "1",
        "NETREGRESS_SESSION_SECRET": "netregress-desktop-smoke-session-secret",
        "NETREGRESS_SESSION_COOKIE_SECURE": "0",
    })
    # PyInstaller stores data under _MEIPASS, but importable Python modules
    # live in the PYZ archive. --confcutdir requires a real filesystem path,
    # so collect the embedded test module by import name and anchor pytest's
    # fixture discovery at the extraction root (never the user's working dir).
    embedded_root = Path(getattr(sys, "_MEIPASS", backend_executable.parent)).resolve()
    if not embedded_root.is_dir():
        raise SmokeFailure("the frozen backend resource root is unavailable")
    packaged_contract_modules = (
        "tests.test_desktop_setup",
        "tests.test_pipeline_orchestration",
        "tests.test_pipeline_runtime",
    )
    pytest_args = [
        "-m", "pytest",
        "--pyargs",
        *packaged_contract_modules,
        "-q",
        "-p", "no:cacheprovider",
        "--confcutdir", str(embedded_root),
    ]
    pytest_result = subprocess.run(
        [
            str(backend_executable.resolve()),
            *pytest_args,
        ],
        cwd=state_root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=360,
        check=False,
    )
    if pytest_result.returncode != 0:
        output = (pytest_result.stdout + "\n" + pytest_result.stderr)[-5000:]
        raise SmokeFailure(
            "the packaged backend could not execute its embedded pytest suite "
            f"(exit {pytest_result.returncode}): {output}"
        )

    worker_result = subprocess.run(
        [
            str(backend_executable.resolve()),
            "scripts/netregress_pipeline_worker.py",
            "--once",
        ],
        cwd=state_root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if worker_result.returncode != 0:
        output = (worker_result.stdout + "\n" + worker_result.stderr)[-5000:]
        raise SmokeFailure(
            "the packaged backend could not dispatch its pipeline worker "
            f"(exit {worker_result.returncode}): {output}"
        )
    lines = [line for line in worker_result.stdout.splitlines() if line.strip()]
    if not lines:
        raise SmokeFailure("the packaged pipeline worker produced no result")
    try:
        worker_state = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise SmokeFailure("the packaged pipeline worker returned invalid JSON") from exc
    if worker_state.get("status") != "IDLE":
        raise SmokeFailure(
            "the packaged pipeline worker did not report an idle, empty queue "
            f"in the isolated smoke database: {worker_state.get('status')!r}"
        )
    return {
        "pytest": "PASS",
        "pytest_summary": (pytest_result.stdout.strip().splitlines()[-1:] or ["completed"])[0],
        "packaged_contract_modules": list(packaged_contract_modules),
        "pipeline_worker": worker_state.get("status"),
    }


def _run_cycle(
    executable: Path,
    state_root: Path,
    *,
    appimage: bool,
    backend_executable: Path | None,
) -> dict:
    data_home = state_root / "data"
    process, _ = _start_app(
        executable, state_root=state_root, label="first-launch", appimage=appimage,
    )
    try:
        first_port, first_log = _wait_backend(data_home, process)
        _create_owner_and_login(first_port, first_run=True)
    finally:
        _stop_app(process)

    databases = list(data_home.rglob("test_results.db"))
    if len(databases) != 1 or not databases[0].is_file():
        raise SmokeFailure(
            "the packaged Runner did not create exactly one persistent SQLite database "
            "inside the XDG user data directory"
        )
    database = databases[0]
    if database.stat().st_size == 0:
        raise SmokeFailure("the persistent SQLite database is empty")

    second, _ = _start_app(
        executable, state_root=state_root, label="second-launch", appimage=appimage,
    )
    try:
        second_port, second_log = _wait_backend(data_home, second)
        _create_owner_and_login(second_port, first_run=False)
    finally:
        _stop_app(second)

    # The database and session-signing secret must remain under user data,
    # independent of the installed application resource directory.
    secrets = list(data_home.rglob("session-secret"))
    if len(secrets) != 1 or secrets[0].stat().st_mode & 0o077:
        raise SmokeFailure("persistent session-signing secret is missing or has broad permissions")
    packaged_children = (
        _run_packaged_backend_checks(
            backend_executable, state_root=state_root, database=database,
        )
        if backend_executable is not None else {"status": "NOT_REQUESTED"}
    )
    return {
        "status": "PASS",
        "first_backend_port": first_port,
        "second_backend_port": second_port,
        "database": str(database),
        "database_bytes": database.stat().st_size,
        "session_secret": str(secrets[0]),
        "backend_logs": [str(first_log), str(second_log)],
        "packaged_backend_children": packaged_children,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path, help="Installed Tauri executable or AppImage.")
    parser.add_argument("--state-root", required=True, type=Path, help="Isolated HOME/XDG state root for this smoke test.")
    parser.add_argument("--label", default="desktop")
    parser.add_argument("--appimage", action="store_true", help="Launch the AppImage directly.")
    parser.add_argument(
        "--backend-executable", type=Path,
        help="Packaged resources/backend/netregress-backend to test frozen child dispatch.",
    )
    args = parser.parse_args(argv)

    if not args.executable.is_file() or not os.access(args.executable, os.X_OK):
        parser.error(f"desktop executable is missing or not executable: {args.executable}")
    if not shutil_which("xvfb-run"):
        parser.error("xvfb-run is required for the headless desktop lifecycle smoke test")

    args.state_root.mkdir(parents=True, exist_ok=True)
    try:
        report = _run_cycle(
            args.executable, args.state_root, appimage=args.appimage,
            backend_executable=args.backend_executable,
        )
        report["label"] = args.label
        report["executable"] = str(args.executable)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        report = {
            "status": "FAIL",
            "label": args.label,
            "executable": str(args.executable),
            "error": f"{type(exc).__name__}: {exc}",
        }
        print(json.dumps(report, indent=2, sort_keys=True), file=sys.stderr)
        return 1


def shutil_which(name: str) -> str | None:
    from shutil import which
    return which(name)


if __name__ == "__main__":
    raise SystemExit(main())
