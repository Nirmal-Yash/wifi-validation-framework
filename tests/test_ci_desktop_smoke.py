from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.ci_desktop_smoke import SmokeFailure, _wait_backend


def test_wait_backend_includes_backend_log_when_desktop_exits(tmp_path):
    data_home = tmp_path / "data"
    backend_log = data_home / "netregress" / "logs" / "backend.log"
    backend_log.parent.mkdir(parents=True)
    backend_log.write_text(
        "Traceback (most recent call last):\\nRuntimeError: backend startup diagnostic\\n",
        encoding="utf-8",
    )
    launcher_log = tmp_path / "launcher.log"
    launcher_log.write_text("Tauri setup failed", encoding="utf-8")
    process = SimpleNamespace(
        poll=lambda: 1,
        returncode=1,
        stdout_path=launcher_log,
    )

    with pytest.raises(SmokeFailure) as failure:
        _wait_backend(data_home, process)

    message = str(failure.value)
    assert "backend startup diagnostic" in message
    assert "Tauri setup failed" in message


def test_packaged_pytest_environment_is_hardware_free(tmp_path, monkeypatch):
    import json
    import subprocess

    from scripts import ci_desktop_smoke

    backend = tmp_path / "netregress-backend"
    backend.write_text("binary-placeholder", encoding="utf-8")
    backend.chmod(0o755)
    database = tmp_path / "data" / "results" / "test_results.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"sqlite-placeholder")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if "-m" in command:
            assert kwargs["env"]["NETREGRESS_CI_MODE"] == "1"
            return subprocess.CompletedProcess(command, 0, "7 passed\\n", "")
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"status": "IDLE"}) + "\n", "",
        )

    monkeypatch.setattr(ci_desktop_smoke.subprocess, "run", fake_run)
    result = ci_desktop_smoke._run_packaged_backend_checks(
        backend, state_root=tmp_path, database=database,
    )

    assert result["pytest"] == "PASS"
    assert result["pipeline_worker"] == "IDLE"
    pytest_command = calls[0][0]
    assert pytest_command[pytest_command.index("--pyargs") + 1] == "tests.test_desktop_setup"
    assert "--confcutdir" in pytest_command
    environment = calls[0][1]["env"]
    assert environment["NETREGRESS_CI_MODE"] == "1"
    assert environment["NETREGRESS_SESSION_COOKIE_SECURE"] == "0"
    assert environment["NETREGRESS_SESSION_SECRET"]
