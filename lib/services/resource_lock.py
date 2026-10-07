from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import fcntl,json,re,time
from pathlib import Path
@dataclass(slots=True)
class ResourceLease:
    resource_id:str; owner:str; path:Path; _handle:object; acquired_at:datetime; expires_at:datetime
    def renew(self,seconds): self.expires_at=datetime.now(timezone.utc)+timedelta(seconds=seconds); self._write()
    def _write(self):
        self._handle.seek(0); self._handle.truncate(); self._handle.write(json.dumps({"resource_id":self.resource_id,"owner":self.owner,"acquired_at":self.acquired_at.isoformat(),"expires_at":self.expires_at.isoformat()},sort_keys=True).encode()); self._handle.flush()
    def release(self):
        try: fcntl.flock(self._handle,fcntl.LOCK_UN)
        finally:
            self._handle.close(); self.path.unlink(missing_ok=True)
class ResourceLockError(RuntimeError): pass
class ResourceLockManager:
    def __init__(self,directory): self.directory=Path(directory); self.directory.mkdir(parents=True,exist_ok=True)
    def acquire(self,resource_id,owner,timeout=0.0,lease_seconds=900.0):
        path=self.directory/(re.sub(r"[^A-Za-z0-9_.-]+","_",resource_id)+".lock"); h=path.open("a+b"); end=time.monotonic()+timeout
        while True:
            try:
                fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB); now=datetime.now(timezone.utc); lease=ResourceLease(resource_id,owner,path,h,now,now+timedelta(seconds=lease_seconds)); lease._write(); return lease
            except BlockingIOError:
                if time.monotonic()>=end: h.close(); raise ResourceLockError(f"resource is already locked: {resource_id}")
                time.sleep(.05)
