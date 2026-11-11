from __future__ import annotations

import os
import stat
import sys

import pytest

from lib.platform import (
    PlatformCapabilityError,
    PlatformFamily,
    SecretStoreError,
    SecretServiceSecretStore,
    SubprocessExecutor,
    UnavailableSecretStore,
    describe_platform,
    platform_adapter_for,
    resolve_application_paths,
)


def test_source_checkout_paths_preserve_legacy_defaults(tmp_path):
    paths = resolve_application_paths(
        tmp_path,
        environ={},
        system="Linux",
        home=tmp_path / "home",
        packaged=False,
    )
    assert paths.data_dir == tmp_path / ".local"
    assert paths.config_dir == tmp_path / "configs"
    assert paths.results_dir == tmp_path / "results"
    assert paths.logs_dir == tmp_path / ".local" / "logs"
    assert paths.database_path == tmp_path / "results" / "test_results.db"


def test_packaged_linux_uses_xdg_locations_without_creating_them(tmp_path):
    home = tmp_path / "home"
    env = {
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
        "XDG_STATE_HOME": str(tmp_path / "xdg-state"),
    }
    paths = resolve_application_paths(tmp_path, environ=env, system="Linux", home=home, packaged=True)
    assert paths.data_dir == tmp_path / "xdg-data" / "netregress"
    assert paths.config_dir == tmp_path / "xdg-config" / "netregress"
    assert paths.cache_dir == tmp_path / "xdg-cache" / "netregress"
    assert paths.state_dir == tmp_path / "xdg-state" / "netregress"
    assert paths.database_path == paths.results_dir / "test_results.db"
    assert not paths.data_dir.exists()


def test_packaged_windows_uses_local_and_roaming_appdata(tmp_path):
    env = {
        "LOCALAPPDATA": str(tmp_path / "LocalAppData"),
        "APPDATA": str(tmp_path / "RoamingAppData"),
    }
    paths = resolve_application_paths(tmp_path, environ=env, system="Windows", home=tmp_path, packaged=True)
    assert paths.data_dir == tmp_path / "LocalAppData" / "NetRegress"
    assert paths.config_dir == tmp_path / "RoamingAppData" / "NetRegress"
    assert paths.results_dir == paths.data_dir / "Results"
    assert paths.family is PlatformFamily.WINDOWS


def test_existing_local_and_database_overrides_remain_supported(tmp_path):
    custom_local = tmp_path / "private"
    custom_db = tmp_path / "db" / "runner.sqlite"
    paths = resolve_application_paths(
        tmp_path,
        environ={
            "NETREGRESS_LOCAL_DIR": str(custom_local),
            "NETREGRESS_DATABASE_PATH": str(custom_db),
        },
        system="Linux",
        home=tmp_path,
        packaged=False,
    )
    assert paths.data_dir == custom_local
    assert paths.state_dir == custom_local
    assert paths.database_path == custom_db


def test_legacy_database_alias_is_preserved(tmp_path):
    expected = tmp_path / "legacy.sqlite"
    paths = resolve_application_paths(
        tmp_path,
        environ={"TEST_DB_PATH": str(expected)},
        system="Linux",
        home=tmp_path,
        packaged=False,
    )
    assert paths.database_path == expected


def test_platform_detection_reports_linux_specific_hwsim_facilities():
    linux = describe_platform("Linux")
    windows = describe_platform("Windows")
    assert linux.capabilities.native_hwsim_kernel is True
    assert linux.capabilities.procfs_process_identity is True
    assert windows.capabilities.native_hwsim_kernel is False
    assert windows.capabilities.procfs_process_identity is False
    assert windows.capabilities.windows_process_groups is True


def test_windows_adapter_fails_closed_for_private_state_and_secrets(tmp_path):
    adapter = platform_adapter_for(describe_platform("Windows"))
    with pytest.raises(PlatformCapabilityError, match="ACL verification"):
        adapter.ensure_private_directory(tmp_path / "private")
    with pytest.raises(SecretStoreError, match="Credential Manager"):
        adapter.create_secret_store().get("router-password")
    assert adapter.provider_availability("hwsim").available is False


def test_unavailable_secret_store_never_returns_a_secret():
    store = UnavailableSecretStore("secure storage not implemented")
    with pytest.raises(SecretStoreError, match="not implemented"):
        store.get("test")


def test_subprocess_executor_is_argument_safe_and_can_terminate_owned_child():
    executor = SubprocessExecutor()
    with pytest.raises(TypeError, match="sequence of arguments"):
        executor.start("echo unsafe")  # type: ignore[arg-type]
    process = executor.start([sys.executable, "-c", "import time; time.sleep(30)"])
    assert process.pid > 0
    assert process.poll() is None
    exit_code = process.terminate(grace_seconds=0.1)
    assert isinstance(exit_code, int)
    assert process.poll() is not None


def test_secret_service_never_places_secret_in_command_arguments(monkeypatch):
    calls = []

    def fake_which(_executable):
        return "/usr/bin/secret-tool"

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("lib.platform.secrets.shutil.which", fake_which)
    store = SecretServiceSecretStore(runner=fake_run)
    store.set("router-password", "a-sensitive-value")
    command, kwargs = calls[0]
    assert "a-sensitive-value" not in command
    assert kwargs["input"] == "a-sensitive-value"
    assert kwargs["capture_output"] is True


def test_linux_private_directory_is_owner_only(tmp_path):
    if os.name != "posix":
        pytest.skip("Unix permission bits are not available")
    adapter = platform_adapter_for(describe_platform("Linux"))
    target = adapter.ensure_private_directory(tmp_path / "private")
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o755)
    unsafe.chmod(0o755)
    with pytest.raises(PlatformCapabilityError, match="group or world permissions"):
        adapter.ensure_private_directory(unsafe)



def test_packaged_macos_uses_application_support_locations(tmp_path):
    paths = resolve_application_paths(
        tmp_path, environ={}, system="Darwin", home=tmp_path / "home", packaged=True
    )
    support = tmp_path / "home" / "Library" / "Application Support" / "NetRegress"
    assert paths.data_dir == support
    assert paths.config_dir == tmp_path / "home" / "Library" / "Preferences" / "NetRegress"
    assert paths.results_dir == support / "Results"


def test_packaged_user_data_override_contains_default_results(tmp_path):
    user_data = tmp_path / "user-data"
    paths = resolve_application_paths(
        tmp_path,
        environ={"NETREGRESS_USER_DATA_DIR": str(user_data)},
        system="Windows",
        home=tmp_path,
        packaged=True,
    )
    assert paths.data_dir == user_data
    assert paths.results_dir == user_data / "Results"
    assert paths.database_path == user_data / "Results" / "test_results.db"
