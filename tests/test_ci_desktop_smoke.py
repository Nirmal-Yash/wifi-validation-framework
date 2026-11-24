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


def test_smoke_owner_password_is_stable_across_invocations(monkeypatch):
    from scripts import ci_desktop_smoke

    password = "ci-smoke-owner-" + ("x" * 40)
    monkeypatch.setenv("NETREGRESS_SMOKE_OWNER_PASSWORD", password)
    assert ci_desktop_smoke._resolve_owner_password() == password
    assert ci_desktop_smoke._resolve_owner_password() == password


def test_smoke_owner_password_rejects_weak_environment_values(monkeypatch):
    from scripts import ci_desktop_smoke

    monkeypatch.setenv("NETREGRESS_SMOKE_OWNER_PASSWORD", "too-short")
    with pytest.raises(RuntimeError, match="long, whitespace-free token"):
        ci_desktop_smoke._resolve_owner_password()


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
    pyargs_index = pytest_command.index("--pyargs")
    expected_modules = [
        "tests.test_desktop_setup",
        "tests.test_project_scope_persistence",
        "tests.test_credential_vault",
        "tests.test_device_inventory",
        "tests.test_configuration_profile_service",
        "tests.test_ansible_automation",
        "tests.test_performance_policy_engine",
        "tests.test_topology_apply",
        "tests.test_configuration_deployer",
        "tests.test_pipeline_orchestration",
        "tests.test_pipeline_runtime",
        "tests.test_release_artifact_verification",
    ]
    assert pytest_command[pyargs_index + 1:pyargs_index + 1 + len(expected_modules)] == expected_modules
    assert result["packaged_contract_modules"] == expected_modules
    assert "--confcutdir" in pytest_command
    environment = calls[0][1]["env"]
    assert environment["NETREGRESS_CI_MODE"] == "1"
    assert environment["NETREGRESS_SESSION_COOKIE_SECURE"] == "0"
    assert environment["NETREGRESS_SESSION_SECRET"]
    assert "NETREGRESS_SMOKE_OWNER_PASSWORD" not in environment


def test_desktop_window_qualification_checks_geometry_focus_and_capture(tmp_path, monkeypatch):
    import subprocess
    from pathlib import Path

    from scripts import ci_desktop_smoke

    monkeypatch.setattr(ci_desktop_smoke, "shutil_which", lambda name: f"/usr/bin/{name}")
    display_path = tmp_path / "xvfb-display.txt"
    display_path.write_text(":99\n/tmp/xvfb-auth\n", encoding="utf-8")
    observed_displays = []

    def fake_run(command, **kwargs):
        observed_displays.append(kwargs.get("env", {}).get("DISPLAY"))
        assert kwargs.get("env", {}).get("XAUTHORITY") == "/tmp/xvfb-auth"
        if command[:3] == ["xdotool", "search", "--onlyvisible"]:
            return subprocess.CompletedProcess(command, 0, "42\n", "")
        if command[:2] == ["xdotool", "getwindowname"]:
            return subprocess.CompletedProcess(command, 0, "NetRegress — Wi-Fi Validation Runner\n", "")
        if command[:2] == ["xdotool", "getwindowgeometry"]:
            return subprocess.CompletedProcess(
                command, 0, "WINDOW=42\nX=10\nY=20\nWIDTH=1480\nHEIGHT=960\nSCREEN=0\n", "",
            )
        if command[:2] == ["xwd", "-silent"]:
            Path(command[command.index("-out") + 1]).write_bytes(b"xwd" + (b"\\0" * 8192))
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ci_desktop_smoke.subprocess, "run", fake_run)
    process = SimpleNamespace(poll=lambda: None, returncode=None, display_path=display_path)
    result = ci_desktop_smoke._qualify_desktop_window(
        process, state_root=tmp_path, label="visible", timeout=1,
    )
    assert result["title"].startswith("NetRegress")
    assert (result["width"], result["height"]) == (1480, 960)
    assert result["keyboard_focus"] == "PASS"
    assert result["screenshot_bytes"] > 4096
    assert set(observed_displays) == {":99"}
    assert (tmp_path / "visible-window.xwd").is_file()


def test_start_app_wraps_application_inside_shared_xvfb_context(tmp_path, monkeypatch):
    import subprocess
    from pathlib import Path

    from scripts import ci_desktop_smoke

    executable = tmp_path / "netregress-runner"
    executable.write_text("placeholder", encoding="utf-8")
    observed = {}

    def fake_popen(command, **kwargs):
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        return SimpleNamespace(pid=42, poll=lambda: None)

    monkeypatch.setattr(ci_desktop_smoke.subprocess, "Popen", fake_popen)
    process, data_home = ci_desktop_smoke._start_app(
        executable,
        state_root=tmp_path / "state",
        label="first-launch",
        appimage=False,
    )
    command = observed["command"]
    script = command[command.index("-c") + 1]
    assert command[0:3] == ["xvfb-run", "-a", "--server-args=-screen 0 1600x1000x24"]
    assert "bash" in command and "xvfb-display.txt" in command[-2]
    assert '"$DISPLAY"' in script and '"${XAUTHORITY:-}"' in script
    assert "NETREGRESS_SMOKE_OWNER_PASSWORD" not in observed["environment"]
    assert process.display_path == Path(command[-2])
    assert process.stdout_path.is_file()
    assert data_home.is_dir()
    process._smoke_output.close()


def test_desktop_window_qualification_fails_when_window_is_not_visible(tmp_path, monkeypatch):
    import subprocess

    from scripts import ci_desktop_smoke

    monkeypatch.setattr(ci_desktop_smoke, "shutil_which", lambda name: f"/usr/bin/{name}")
    display_path = tmp_path / "xvfb-display.txt"
    display_path.write_text(":99\n/tmp/xvfb-auth\n", encoding="utf-8")
    monkeypatch.setattr(
        ci_desktop_smoke.subprocess, "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "no window"),
    )
    process = SimpleNamespace(poll=lambda: None, returncode=None, display_path=display_path)
    with pytest.raises(SmokeFailure, match="did not pass visibility/render/focus qualification"):
        ci_desktop_smoke._qualify_desktop_window(
            process, state_root=tmp_path, label="missing", timeout=0.01,
        )
