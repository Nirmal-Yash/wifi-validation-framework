from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import multiprocessing
import os
import time

import pytest

from lib.services.operational_recovery import StaleLockRecovery
from lib.services.resource_lock import (
    ResourceLockError,
    ResourceLockManager,
)


def _hold_resource_lock(directory: str, ready, release) -> None:
    manager = ResourceLockManager(directory)
    lease = manager.acquire("lab:shared", "child-process", timeout=1)
    ready.set()
    release.wait(5)
    lease.release()


def test_exclusive_lock_and_idempotent_release(tmp_path):
    manager = ResourceLockManager(tmp_path)
    first = manager.acquire("lab:one", "owner-1")
    lock_path = first.path
    original_inode = lock_path.stat().st_ino
    try:
        with pytest.raises(ResourceLockError):
            manager.acquire("lab:one", "owner-2")
    finally:
        first.release()
        first.release()

    assert lock_path.exists()
    assert lock_path.stat().st_ino == original_inode
    second = manager.acquire("lab:one", "owner-2")
    assert second.path == lock_path
    second.release()


def test_cross_process_exclusion_uses_the_same_lock_inode(tmp_path):
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    release = context.Event()
    child = context.Process(
        target=_hold_resource_lock,
        args=(str(tmp_path), ready, release),
    )
    child.start()
    try:
        assert ready.wait(3), "child did not acquire the resource lock"
        manager = ResourceLockManager(tmp_path)
        path = manager._lock_path("lab:shared")
        inode = path.stat().st_ino
        with pytest.raises(ResourceLockError):
            manager.acquire("lab:shared", "parent-process", timeout=0.1)
        assert path.stat().st_ino == inode
    finally:
        release.set()
        child.join(5)
        if child.is_alive():
            child.terminate()
            child.join(2)
    assert child.exitcode == 0

    lease = ResourceLockManager(tmp_path).acquire("lab:shared", "parent-after-child")
    assert lease.path.stat().st_ino == inode
    lease.release()


def test_resource_names_that_sanitize_identically_do_not_collide(tmp_path):
    manager = ResourceLockManager(tmp_path)
    first = manager._lock_path("lab:a/b")
    second = manager._lock_path("lab:a_b")
    assert first != second


def test_lease_renewal_updates_expiry_and_released_lease_cannot_renew(tmp_path):
    manager = ResourceLockManager(tmp_path)
    lease = manager.acquire("device:ap-1", "owner", lease_seconds=10)
    previous = lease.expires_at
    lease.renew(60)
    assert lease.expires_at > previous
    metadata = json.loads(lease.path.read_text(encoding="utf-8"))
    assert metadata["state"] == "HELD"
    assert metadata["expires_at"] == lease.expires_at.isoformat()

    lease.release()
    with pytest.raises(ResourceLockError, match="released"):
        lease.renew(60)


def test_acquire_many_rolls_back_partial_acquisition(tmp_path):
    manager = ResourceLockManager(tmp_path)
    occupied = manager.acquire("resource:b", "other-owner")
    try:
        with pytest.raises(ResourceLockError):
            manager.acquire_many(["resource:a", "resource:b"], "group-owner")
        # resource:a was acquired before b failed and must have been released.
        recovered = manager.acquire("resource:a", "next-owner")
        recovered.release()
    finally:
        occupied.release()


def test_acquire_many_releases_all_locks_idempotently(tmp_path):
    manager = ResourceLockManager(tmp_path)
    group = manager.acquire_many(["lab:one", "device:ap"], "run-owner")
    assert len(group.paths) == 2
    group.release()
    group.release()
    for resource in ("lab:one", "device:ap"):
        lease = manager.acquire(resource, "next-owner")
        lease.release()


def test_invalid_lease_durations_fail_closed(tmp_path):
    manager = ResourceLockManager(tmp_path)
    for value in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            manager.acquire("lab:one", "owner", lease_seconds=value)
    with pytest.raises(ValueError):
        manager.acquire("lab:one", "owner", timeout=-1)


def _write_stale_metadata(path, *, owner="runner:99999999:dead"):
    payload = {
        "schema_version": 1,
        "resource_id": "lab:stale",
        "owner": owner,
        "state": "HELD",
        "acquired_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_stale_recovery_marks_metadata_without_unlinking_inode(tmp_path):
    manager = ResourceLockManager(tmp_path)
    path = manager._lock_path("lab:stale")
    path.touch()
    inode = path.stat().st_ino
    _write_stale_metadata(path)

    recovery = StaleLockRecovery()
    observed = recovery.inspect(tmp_path)
    assert len(observed) == 1
    assert observed[0]["expired"] is True
    assert observed[0]["owner_alive"] is False
    assert observed[0]["locked"] is False

    assert recovery.recover(tmp_path) == 1
    assert path.exists()
    assert path.stat().st_ino == inode
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "RECOVERED"
    assert recovery.recover(tmp_path) == 0


def test_stale_recovery_never_reclaims_an_expired_but_locked_inode(tmp_path):
    manager = ResourceLockManager(tmp_path)
    lease = manager.acquire("lab:stale", "runner:99999999:dead", lease_seconds=1)
    lease.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    lease._write()
    try:
        recovery = StaleLockRecovery()
        observed = recovery.inspect(tmp_path)
        assert observed[0]["expired"] is True
        assert observed[0]["owner_alive"] is False
        assert observed[0]["locked"] is True
        assert recovery.recover(tmp_path) == 0
        assert json.loads(lease.path.read_text(encoding="utf-8"))["state"] == "HELD"
    finally:
        lease.release()


def test_lock_manager_refuses_symlink_lock_paths(tmp_path):
    manager = ResourceLockManager(tmp_path)
    target = tmp_path / "external-target"
    target.write_text("do-not-modify", encoding="utf-8")
    path = manager._lock_path("lab:symlink")
    path.symlink_to(target)

    with pytest.raises(ResourceLockError, match="cannot safely open"):
        manager.acquire("lab:symlink", "attacker")

    assert target.read_text(encoding="utf-8") == "do-not-modify"
