from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,platform,socket,subprocess
from pathlib import Path
from typing import Any,Mapping
@dataclass(frozen=True,slots=True)
class EnvironmentFingerprint: fingerprint:str; captured_at:datetime; payload:Mapping[str,Any]
class EnvironmentFingerprintService:
    def __init__(self,root): self.root=Path(root).resolve()
    def capture(self,*,lab_id,configuration_hash,topology=None,device_identity=None,observations=None):
        payload={"lab_id":lab_id,"configuration_hash":configuration_hash,"host":{"hostname":socket.gethostname(),"os":platform.platform(),"kernel":platform.release(),"python":platform.python_version(),"architecture":platform.machine()},"repository_commit":self._git_commit(),"interfaces":self._interfaces(),"topology":dict(topology or {}),"device_identity":dict(device_identity or {}),"observations":dict(observations or {})}
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return EnvironmentFingerprint(digest,datetime.now(timezone.utc),payload)
    def _git_commit(self):
        try:return subprocess.run(["git","rev-parse","HEAD"],cwd=self.root,capture_output=True,text=True,timeout=5,check=True).stdout.strip() or "unknown"
        except (OSError,subprocess.SubprocessError):return "unknown"
    @staticmethod
    def _interfaces():
        p=Path("/sys/class/net"); return tuple(sorted(x.name for x in p.iterdir())) if p.is_dir() else ()
