from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Sequence

@dataclass(frozen=True, slots=True)
class BackupResult:
    source: Path
    destination: Path
    integrity_ok: bool
    size_bytes: int
    sha256: str = ""


class SQLiteBackupService:
    """Consistent SQLite online backups with integrity and overwrite safeguards."""

    @staticmethod
    def _integrity(path: Path) -> str:
        connection = sqlite3.connect(path, timeout=15)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            return str(row[0]) if row else "no result"
        finally:
            connection.close()

    @staticmethod
    def _digest(path: Path) -> str:
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _copy(
        self,
        source: str | Path,
        destination: str | Path,
        *,
        overwrite: bool,
    ) -> BackupResult:
        import os
        import tempfile

        src = Path(source).expanduser().resolve()
        dst = Path(destination).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(src)
        if src == dst:
            raise ValueError("backup destination must differ from source")
        if dst.exists() and not overwrite:
            raise FileExistsError(dst)
        if self._integrity(src) != "ok":
            raise sqlite3.DatabaseError(f"source database integrity check failed: {src}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{dst.name}.", suffix=".sqlite.tmp", dir=dst.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            source_db = sqlite3.connect(src, timeout=15)
            target_db = sqlite3.connect(temporary, timeout=15)
            try:
                source_db.backup(target_db, pages=256, sleep=0.05)
                target_db.execute("PRAGMA integrity_check").fetchone()
            finally:
                target_db.close()
                source_db.close()
            integrity = self._integrity(temporary)
            if integrity != "ok":
                raise sqlite3.DatabaseError(
                    f"backup integrity check failed: {integrity}"
                )
            os.chmod(temporary, 0o600)
            if overwrite:
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(dst) + suffix)
                    if sidecar.exists():
                        sidecar.unlink()
                os.replace(temporary, dst)
            else:
                # A hard link makes destination creation atomic and refuses a
                # concurrent writer that created the same backup name.
                os.link(temporary, dst)
                temporary.unlink()
            return BackupResult(
                source=src,
                destination=dst,
                integrity_ok=True,
                size_bytes=dst.stat().st_size,
                sha256=self._digest(dst),
            )
        finally:
            if temporary.exists():
                temporary.unlink()

    def backup(self, source: str | Path, destination: str | Path) -> BackupResult:
        return self._copy(source, destination, overwrite=False)

    def restore(self, backup: str | Path, destination: str | Path) -> BackupResult:
        return self._copy(backup, destination, overwrite=True)


@dataclass(frozen=True, slots=True)
class RetentionResult:
    removed_files: int
    removed_bytes: int

class RetentionService:
    def prune(self, root: str | Path, *, older_than_seconds: int, suffixes: Iterable[str] = ()) -> RetentionResult:
        base=Path(root).resolve()
        if not base.is_dir():
            return RetentionResult(0,0)
        now=time.time()
        allowed={suffix.lower() for suffix in suffixes}
        removed_files=removed_bytes=0
        for path in base.rglob("*"):
            if not path.is_file(): continue
            if allowed and path.suffix.lower() not in allowed: continue
            if now - path.stat().st_mtime <= older_than_seconds: continue
            size=path.stat().st_size
            path.unlink()
            removed_files += 1
            removed_bytes += size
        return RetentionResult(removed_files,removed_bytes)

class StaleLockRecovery:
    """Inspect and clear stale metadata without ever unlinking lock inodes."""

    @staticmethod
    def _owner_alive(owner: str | None) -> bool:
        if not owner or not owner.startswith("runner:"):
            return False
        try:
            pid = int(owner.split(":", 2)[1])
            if pid <= 1:
                return False
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except (ValueError, IndexError):
            return False

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, object]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def inspect(self, lock_dir: str | Path) -> tuple[dict[str, object], ...]:
        root = Path(lock_dir).resolve()
        if not root.is_dir():
            return ()
        now = datetime.now(timezone.utc)
        results = []
        for path in sorted(root.glob("*.lock")):
            metadata = self._read_metadata(path)
            try:
                expires = datetime.fromisoformat(str(metadata["expires_at"]))
                owner = str(metadata.get("owner", ""))
                expired = expires <= now
            except (ValueError, TypeError, KeyError):
                owner = str(metadata.get("owner", "")) or None
                expired = True

            descriptor = None
            locked = True
            try:
                flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                descriptor = os.open(path, flags)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = False
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except BlockingIOError:
                    locked = True
            except OSError:
                locked = True
            finally:
                if descriptor is not None:
                    os.close(descriptor)

            results.append({
                "path": str(path),
                "resource_id": metadata.get("resource_id"),
                "owner": owner,
                "state": metadata.get("state", "UNKNOWN"),
                "expired": expired,
                "owner_alive": self._owner_alive(owner),
                "locked": locked,
            })
        return tuple(results)

    def recover(self, lock_dir: str | Path) -> int:
        """Mark abandoned, unlocked leases recovered; preserve each lock inode."""
        root = Path(lock_dir).resolve()
        if not root.is_dir():
            return 0
        recovered = 0
        now = datetime.now(timezone.utc)
        for item in self.inspect(root):
            if (
                not item["expired"]
                or item["owner_alive"]
                or item["locked"]
                or item["state"] not in {"HELD", "UNKNOWN"}
            ):
                continue
            path = Path(str(item["path"]))
            descriptor = None
            try:
                flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                descriptor = os.open(path, flags)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                with os.fdopen(os.dup(descriptor), "r+b") as handle:
                    handle.seek(0)
                    try:
                        metadata = json.load(handle)
                    except (ValueError, TypeError):
                        metadata = {}
                    if not isinstance(metadata, dict):
                        metadata = {}
                    metadata.update({
                        "state": "RECOVERED",
                        "expires_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                    })
                    handle.seek(0)
                    handle.truncate(0)
                    handle.write(json.dumps(
                        metadata, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
                recovered += 1
            except OSError:
                continue
            finally:
                if descriptor is not None:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    finally:
                        os.close(descriptor)
        return recovered

class RunRecoveryService:
    """Classify abandoned RUNNING Runs after a process/host restart."""
    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0: return False
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return isinstance(pid, int)
    def recover_orphaned_runs(self, run_service) -> tuple[str, ...]:
        recovered=[]
        for run in run_service.run_repository.list():
            if run.lifecycle.value != "RUNNING" or not run.execution_pid:
                continue
            if self._pid_alive(int(run.execution_pid)):
                continue
            run_service.worker_crashed(run.run_id, "Runner restarted while Run was RUNNING")
            recovered.append(run.run_id)
        return tuple(recovered)

class AuditIntegrityService:
    @staticmethod
    def digest(events: Sequence[object]) -> str:
        previous="0"*64
        for event in events:
            payload={
                "previous":previous,
                "event_id":getattr(event,"event_id",""),
                "run_id":getattr(event,"run_id",""),
                "attempt_id":getattr(event,"attempt_id",None),
                "test_result_id":getattr(event,"test_result_id",None),
                "event_type":getattr(event,"event_type",""),
                "occurred_at":getattr(event,"occurred_at").isoformat() if getattr(event,"occurred_at",None) else None,
                "details":dict(getattr(event,"details",{}) or {}),
            }
            previous=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return previous
