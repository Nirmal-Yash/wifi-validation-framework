from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from lib.platform.desktop_runtime import prepare_desktop_runtime
from lib.platform.contracts import PlatformCapabilityError
from lib.services.run_process import RunProcessManager


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "HOME": str(tmp_path / "home"),
        "NETREGRESS_USER_DATA_DIR": str(tmp_path / "home" / "data"),
        "NETREGRESS_CONFIG_DIR": str(tmp_path / "home" / "config"),
    }


def test_desktop_runtime_uses_private_persistent_paths_and_session_secret(tmp_path):
    env = _environment(tmp_path)
    home = Path(env["HOME"])
    runtime = prepare_desktop_runtime(
        tmp_path / "bundle", environ=env, home=home, port=51437,
    )

    assert runtime.paths.packaged is True
    assert runtime.paths.database_path == home / "data" / "results" / "test_results.db"
    assert env["NETREGRESS_PORT"] == "51437"
    assert env["NETREGRESS_AUTH_REQUIRED"] == "1"
    assert env["NETREGRESS_SESSION_COOKIE_SAMESITE"] == "None"
    assert env["NETREGRESS_SESSION_COOKIE_SECURE"] == "1"
    assert Path(env["NETREGRESS_PROCESS_DIR"]) == runtime.paths.results_dir / "processes"
    assert stat.S_IMODE(runtime.paths.data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(runtime.paths.results_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(runtime.session_secret_file.stat().st_mode) == 0o600
    first_secret = runtime.session_secret_file.read_text(encoding="ascii")
    assert len(first_secret) == 64

    second = prepare_desktop_runtime(
        tmp_path / "bundle", environ=env, home=home, port=51437,
    )
    assert second.session_secret_file.read_text(encoding="ascii") == first_secret


def test_desktop_runtime_rejects_a_world_readable_session_secret(tmp_path):
    env = _environment(tmp_path)
    runtime = prepare_desktop_runtime(
        tmp_path / "bundle", environ=env, home=Path(env["HOME"]), port=51437,
    )
    runtime.session_secret_file.chmod(0o644)

    with pytest.raises(RuntimeError, match="permissions must be 0600"):
        prepare_desktop_runtime(
            tmp_path / "bundle", environ=env, home=Path(env["HOME"]), port=51437,
        )


def test_desktop_runtime_rejects_symlinked_private_state(tmp_path):
    target = tmp_path / "shared"
    target.mkdir()
    link = tmp_path / "home"
    link.symlink_to(target, target_is_directory=True)
    env = {
        "HOME": str(link),
        "NETREGRESS_USER_DATA_DIR": str(link / "data"),
        "NETREGRESS_CONFIG_DIR": str(link / "config"),
    }
    with pytest.raises(PlatformCapabilityError, match="must not be a symlink"):
        prepare_desktop_runtime(
            tmp_path / "bundle", environ=env, home=link, port=51437,
        )


@pytest.mark.parametrize("port", [0, 80, 65536, True])
def test_desktop_runtime_rejects_invalid_backend_ports(tmp_path, port):
    env = _environment(tmp_path)
    with pytest.raises(ValueError, match="port"):
        prepare_desktop_runtime(
            tmp_path / "bundle", environ=env, home=Path(env["HOME"]), port=port,
        )


def test_run_process_manager_writes_process_logs_to_configured_user_data(monkeypatch, tmp_path):
    expected = tmp_path / "persisted" / "processes"
    monkeypatch.setenv("NETREGRESS_PROCESS_DIR", str(expected))
    manager = RunProcessManager(tmp_path / "immutable-bundle")

    assert manager.root == (tmp_path / "immutable-bundle").resolve()
    assert manager.process_dir == expected.resolve()
