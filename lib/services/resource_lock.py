from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Iterable, Sequence, BinaryIO


class ResourceLockError(RuntimeError):
    """A resource lease could not be safely acquired or maintained."""


def _validate_duration(name: str, value: float, *, allow_zero: bool) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(seconds) or seconds < 0 or (not allow_zero and seconds == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return seconds


@dataclass(slots=True)
class ResourceLease:
    resource_id: str
    owner: str
    path: Path
    _handle: BinaryIO = field(repr=False)
    acquired_at: datetime
    expires_at: datetime
    _released: bool = field(default=False, init=False, repr=False)

    @property
    def active(self) -> bool:
        return not self._released

    def renew(self, seconds: float) -> None:
        if self._released:
            raise ResourceLockError("cannot renew a released resource lease")
        lifetime = _validate_duration("lease_seconds", seconds, allow_zero=False)
        self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=lifetime)
        self._write(state="HELD")

    def _write(self, *, state: str = "HELD") -> None:
        if self._released:
            raise ResourceLockError("resource lease is already released")
        payload = {
            "schema_version": 1,
            "resource_id": self.resource_id,
            "owner": self.owner,
            "state": state,
            "acquired_at": self.acquired_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        self._handle.seek(0)
        self._handle.truncate(0)
        self._handle.write(encoded)
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def release(self) -> None:
        if self._released:
            return
        try:
            # Keep the lock pathname/inode stable for waiters and future owners.
            self._write(state="RELEASED")
        finally:
            self._released = True
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()


@dataclass(slots=True)
class ResourceLeaseGroup:
    """A set of resource locks acquired in deterministic order."""

    leases: tuple[ResourceLease, ...]
    _released: bool = field(default=False, init=False, repr=False)

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(lease.path for lease in self.leases)

    @property
    def active(self) -> bool:
        return not self._released

    def renew(self, seconds: float) -> None:
        if self._released:
            raise ResourceLockError("cannot renew a released resource lease group")
        renewed: list[ResourceLease] = []
        try:
            for lease in self.leases:
                lease.renew(seconds)
                renewed.append(lease)
        except Exception:
            # Keep the group usable; caller may release it after a partial renewal.
            raise

    def release(self) -> None:
        if self._released:
            return
        first_error: Exception | None = None
        for lease in reversed(self.leases):
            try:
                lease.release()
            except Exception as exc:  # release all remaining leases regardless
                first_error = first_error or exc
        self._released = True
        if first_error is not None:
            raise ResourceLockError(
                f"one or more resource leases failed to release: {first_error}"
            ) from first_error


class ResourceLockManager:
    """Cross-process advisory resource locks with stable, collision-resistant paths.

    Lock files are persistent by design. flock ownership is released on close or
    process exit; the pathname is never removed, so waiters always contend on the
    same inode.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            self.directory.chmod(0o700)
        except OSError:
            pass

    @staticmethod
    def _validate_identity(name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        return value.strip()

    def _lock_path(self, resource_id: str) -> Path:
        resource_id = self._validate_identity("resource_id", resource_id)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", resource_id).strip("._-")[:48]
        digest = hashlib.sha256(resource_id.encode("utf-8")).hexdigest()[:16]
        return self.directory / f"{safe or 'resource'}-{digest}.lock"

    def acquire(
        self,
        resource_id: str,
        owner: str,
        timeout: float = 0.0,
        lease_seconds: float = 900.0,
    ) -> ResourceLease:
        resource_id = self._validate_identity("resource_id", resource_id)
        owner = self._validate_identity("owner", owner)
        wait = _validate_duration("timeout", timeout, allow_zero=True)
        lifetime = _validate_duration(
            "lease_seconds", lease_seconds, allow_zero=False
        )
        path = self._lock_path(resource_id)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise ResourceLockError(f"cannot safely open resource lock {path}: {exc}") from exc

        handle = os.fdopen(descriptor, "r+b", buffering=0)
        end = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                now = datetime.now(timezone.utc)
                lease = ResourceLease(
                    resource_id, owner, path, handle, now,
                    now + timedelta(seconds=lifetime)
                )
                try:
                    lease._write()
                    os.chmod(path, 0o600)
                except Exception:
                    lease.release()
                    raise
                return lease
            except BlockingIOError:
                if time.monotonic() >= end:
                    handle.close()
                    raise ResourceLockError(
                        f"resource is already locked: {resource_id}"
                    )
                time.sleep(min(0.05, max(0.0, end - time.monotonic())))
            except Exception:
                if not handle.closed:
                    handle.close()
                raise

    def acquire_many(
        self,
        resource_ids: Iterable[str],
        owner: str,
        *,
        timeout: float = 0.0,
        lease_seconds: float = 900.0,
    ) -> ResourceLeaseGroup:
        resources = tuple(sorted({self._validate_identity("resource_id", r) for r in resource_ids}))
        if not resources:
            raise ValueError("at least one resource_id is required")
        acquired: list[ResourceLease] = []
        try:
            for resource_id in resources:
                acquired.append(
                    self.acquire(
                        resource_id,
                        owner,
                        timeout=timeout,
                        lease_seconds=lease_seconds,
                    )
                )
            return ResourceLeaseGroup(tuple(acquired))
        except Exception:
            for lease in reversed(acquired):
                try:
                    lease.release()
                except Exception:
                    pass
            raise
