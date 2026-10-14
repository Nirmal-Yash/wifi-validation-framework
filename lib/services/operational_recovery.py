from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
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

class SQLiteBackupService:
    def backup(self, source: str | Path, destination: str | Path) -> BackupResult:
        src, dst = Path(source).resolve(), Path(destination).resolve()
        if not src.is_file():
            raise FileNotFoundError(src)
        if src == dst:
            raise ValueError("backup destination must differ from source")
        dst.parent.mkdir(parents=True, exist_ok=True)
        source_db = sqlite3.connect(src)
        target_db = sqlite3.connect(dst)
        try:
            source_db.backup(target_db)
        finally:
            target_db.close()
            source_db.close()
        check = sqlite3.connect(dst)
        try:
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            check.close()
        return BackupResult(src, dst, integrity == "ok", dst.stat().st_size)

    def restore(self, backup: str | Path, destination: str | Path) -> BackupResult:
        return self.backup(backup, destination)

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
    def inspect(self, lock_dir: str | Path) -> tuple[dict[str, object], ...]:
        root=Path(lock_dir).resolve()
        if not root.is_dir(): return ()
        now=datetime.now(timezone.utc)
        result=[]
        for path in sorted(root.glob("*.lock")):
            try:
                data=json.loads(path.read_text(encoding="utf-8"))
                expires=datetime.fromisoformat(data["expires_at"])
                owner=str(data["owner"])
                pid=int(owner.split(":")[1]) if owner.startswith("runner:") else None
                alive=True
                if pid:
                    try: os.kill(pid,0)
                    except ProcessLookupError: alive=False
                    except PermissionError: alive=True
                result.append({"path":str(path),"resource_id":data.get("resource_id"),"owner":owner,"expired":expires<=now,"owner_alive":alive})
            except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError):
                result.append({"path":str(path),"resource_id":None,"owner":None,"expired":True,"owner_alive":False})
        return tuple(result)
    def recover(self, lock_dir: str | Path) -> int:
        removed=0
        for item in self.inspect(lock_dir):
            if item["expired"] and not item["owner_alive"]:
                Path(str(item["path"])).unlink(missing_ok=True)
                removed += 1
        return removed

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
