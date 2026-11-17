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
