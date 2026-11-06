from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


class RunProcessError(RuntimeError):
    """Base error for Runner-owned process lifecycle failures."""


class ProcessNotManagedError(RunProcessError):
    """The PID was not started and recorded by this Runner."""


class ProcessOwnershipError(RunProcessError):
    """The PID/process group no longer matches its recorded identity."""


class ProcessTerminationError(RunProcessError):
    """A process group remained alive after termination escalation."""


@dataclass(frozen=True, slots=True)
class RunProcessHandle:
    pid: int
    command: tuple[str, ...]
    log_path: str


class RunProcessManager:
    """Launch and terminate only process groups created by this Runner.

    A private manifest binds the PID/PGID/SID to the Linux /proc start-time
    token. Signals are sent to the recorded process group only after that
    identity is checked, preventing stale/reused PIDs from targeting unrelated
    processes. Child stdout/stderr is retained under results/processes/.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.process_dir = self.root / "results" / "processes"

    def start(
        self,
        *,
        tests: Sequence[str] | None = None,
        firmware_version: str = "v1.0",
        env: Mapping[str, str] | None = None,
    ) -> RunProcessHandle:
        command = [sys.executable, "-m", "pytest"]
        if tests:
            command.extend(str(test) for test in tests)
        command.extend(["-v", f"--firmware-version={firmware_version}"])
        return self._start_command(command, env=env)

    def _start_command(
        self, command: Sequence[str], *, env: Mapping[str, str] | None = None
    ) -> RunProcessHandle:
        args = tuple(str(part) for part in command)
        if not args or not args[0]:
            raise ValueError("process command must not be empty")

        self.process_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.process_dir.chmod(0o700)
        except OSError:
            pass

        pid: int | None = None
        process: subprocess.Popen | None = None
        manifest: dict[str, object] | None = None
        log_path = self.process_dir / f"pytest-{time.time_ns()}.log"
        child_env = os.environ.copy()
        child_env.update({str(key): str(value) for key, value in (env or {}).items()})

        try:
            with log_path.open("ab") as output:
                try:
                    os.chmod(log_path, 0o600)
                except OSError:
                    pass
                process = subprocess.Popen(
                    args,
                    cwd=self.root,
                    env=child_env,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
            pid = process.pid
            identity = self._read_proc_stat(pid)
            if identity is None:
                raise ProcessOwnershipError(
                    f"cannot verify newly started process {pid} through Linux /proc"
                )
            if identity["pgrp"] != pid or identity["session"] != pid:
                raise ProcessOwnershipError(
                    f"new process {pid} is not the expected session leader"
                )
            manifest = {
                "version": 1,
                "pid": pid,
                "process_group": pid,
                "session_id": pid,
                "start_ticks": identity["start_ticks"],
                "command": list(args),
                "cwd": str(self.root),
                "log_path": str(log_path),
                "created_at_ns": time.time_ns(),
            }
            self._write_manifest(pid, manifest)
            threading.Thread(
                target=self._reap_when_finished,
                args=(process, manifest),
                name=f"netregress-reaper-{pid}",
                daemon=True,
            ).start()
            return RunProcessHandle(pid, args, str(log_path))
        except Exception:
            if pid is not None:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                if process is not None:
                    try:
                        process.wait(timeout=2)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
                if manifest is not None:
                    self._remove_manifest(pid, manifest)
            log_path.unlink(missing_ok=True)
            raise

    def validate(self, pid: int) -> bool:
        """Return whether PID is a live, verified Runner-owned process group."""
        manifest = self._load_manifest(pid)
        members = self._validated_group_members(pid, manifest)
        if not members:
            self._remove_manifest(pid, manifest)
            return False
        return True

    def cancel(
        self, pid: int, *, grace_seconds: float = 5.0, kill_timeout: float = 2.0
    ) -> bool:
        """Send SIGTERM, then SIGKILL if needed; return False if already exited."""
        if grace_seconds < 0 or kill_timeout < 0:
            raise ValueError("termination timeouts must be non-negative")
        manifest = self._load_manifest(pid)
        members = self._validated_group_members(pid, manifest)
        if not members:
            self._remove_manifest(pid, manifest)
            return False

        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            members = []
        except OSError as exc:
            raise RunProcessError(f"cannot send SIGTERM to Runner process group {pid}: {exc}") from exc
        if self._wait_for_group_exit(pid, manifest, grace_seconds):
            self._remove_manifest(pid, manifest)
            return True

        # Revalidate after the grace period before escalating.
        members = self._validated_group_members(pid, manifest)
        if members:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                raise RunProcessError(f"cannot send SIGKILL to Runner process group {pid}: {exc}") from exc
        if not self._wait_for_group_exit(pid, manifest, kill_timeout):
            raise ProcessTerminationError(
                f"process group {pid} remained alive after SIGTERM/SIGKILL"
            )
        self._remove_manifest(pid, manifest)
        return True

    def kill(self, pid: int, *, timeout: float = 2.0) -> bool:
        """Immediately SIGKILL a verified Runner-owned process group."""
        if timeout < 0:
            raise ValueError("termination timeout must be non-negative")
        manifest = self._load_manifest(pid)
        members = self._validated_group_members(pid, manifest)
        if not members:
            self._remove_manifest(pid, manifest)
            return False
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise RunProcessError(f"cannot send SIGKILL to Runner process group {pid}: {exc}") from exc
        if not self._wait_for_group_exit(pid, manifest, timeout):
            raise ProcessTerminationError(f"process group {pid} did not exit")
        self._remove_manifest(pid, manifest)
        return True

    def _manifest_path(self, pid: int) -> Path:
        return self.process_dir / f"{int(pid)}.json"

    def _write_manifest(self, pid: int, manifest: dict[str, object]) -> None:
        path = self._manifest_path(pid)
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                old_members = self._validated_group_members(pid, old)
            except RunProcessError:
                old_members = []
            if old_members:
                raise ProcessOwnershipError(
                    f"refusing to replace an active process manifest for PID {pid}"
                )
            path.unlink(missing_ok=True)

        temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            temporary.unlink(missing_ok=True)

    def _load_manifest(self, pid: int) -> dict[str, object]:
        if int(pid) <= 1:
            raise ProcessNotManagedError("invalid Runner process ID")
        path = self._manifest_path(pid)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProcessNotManagedError(
                f"PID {pid} has no Runner process ownership record"
            ) from exc
        except (OSError, ValueError, TypeError) as exc:
            raise ProcessOwnershipError(
                f"PID {pid} has an invalid Runner process ownership record"
            ) from exc
        if (
            manifest.get("version") != 1
            or manifest.get("pid") != int(pid)
            or manifest.get("process_group") != int(pid)
            or manifest.get("session_id") != int(pid)
            or not isinstance(manifest.get("start_ticks"), int)
        ):
            raise ProcessOwnershipError(f"PID {pid} ownership record is inconsistent")
        return manifest

    @staticmethod
    def _read_proc_stat(pid: int) -> dict[str, int | str] | None:
        """Read identity fields from /proc/PID/stat; Linux is the Runner target."""
        try:
            raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            return None
        closing = raw.rfind(")")
        if closing < 0:
            return None
        fields = raw[closing + 2 :].split()
        try:
            return {
                "state": fields[0],
                "pgrp": int(fields[2]),
                "session": int(fields[3]),
                "start_ticks": int(fields[19]),
            }
        except (IndexError, ValueError):
            return None

    @classmethod
    def _group_members(cls, pid: int) -> list[tuple[int, dict[str, int | str]]]:
        proc = Path("/proc")
        if not proc.is_dir():
            raise RunProcessError("safe process ownership checks require Linux /proc")
        members: list[tuple[int, dict[str, int | str]]] = []
        try:
            entries = list(proc.iterdir())
        except OSError as exc:
            raise RunProcessError(f"cannot inspect Linux process table: {exc}") from exc
        for entry in entries:
            if not entry.name.isdigit():
                continue
            identity = cls._read_proc_stat(int(entry.name))
            if identity is None:
                continue
            if (
                identity["pgrp"] == pid
                and identity["session"] == pid
                and identity["state"] not in {"Z", "X"}
            ):
                members.append((int(entry.name), identity))
        return members

    @classmethod
    def _validated_group_members(
        cls, pid: int, manifest: dict[str, object]
    ) -> list[tuple[int, dict[str, int | str]]]:
        members = cls._group_members(pid)
        leader = next((item for item in members if item[0] == pid), None)
        if leader is not None and leader[1]["start_ticks"] != manifest["start_ticks"]:
            raise ProcessOwnershipError(
                f"PID {pid} has been reused; refusing to signal its process group"
            )
        return members

    def _wait_for_group_exit(
        self, pid: int, manifest: dict[str, object], timeout: float
    ) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            members = self._validated_group_members(pid, manifest)
            if not members:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def _remove_manifest(self, pid: int, manifest: dict[str, object]) -> None:
        path = self._manifest_path(pid)
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return
        if (
            current.get("pid") == pid
            and current.get("start_ticks") == manifest.get("start_ticks")
        ):
            path.unlink(missing_ok=True)

    def _reap_when_finished(
        self, process: subprocess.Popen, manifest: dict[str, object]
    ) -> None:
        pid = int(manifest["pid"])
        try:
            process.wait()
            # A child may outlive the pytest leader. Keep the manifest until
            # every member of the original session/process group has exited.
            if self._wait_for_group_exit(pid, manifest, 5.0):
                self._remove_manifest(pid, manifest)
        except (OSError, RunProcessError):
            # A stale record is safe: future cancellation still validates it
            # against /proc and refuses to signal a reused PID.
            return
