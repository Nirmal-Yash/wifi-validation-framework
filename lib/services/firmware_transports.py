from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Protocol

class FirmwareTransferError(RuntimeError): pass
class FirmwareTransfer(Protocol):
    def upload(self,local_path:str|Path,remote_path:str)->str: ...

@dataclass(frozen=True,slots=True)
class TftpFirmwareTransport:
    host:str
    timeout_sec:int=30
    mode:str="binary"
    def upload(self,local_path:str|Path,remote_path:str)->str:
        if not remote_path.startswith("/") or ".." in remote_path.split("/"): raise ValueError("invalid TFTP remote path")
        source=str(Path(local_path).resolve())
        command=["tftp",self.host,"-m",self.mode,"-c","put",source,remote_path]
        try:
            result=subprocess.run(command,capture_output=True,text=True,timeout=self.timeout_sec,check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise FirmwareTransferError(str(exc)) from exc
        if result.returncode!=0: raise FirmwareTransferError(result.stderr.strip() or result.stdout.strip() or f"TFTP failed with code {result.returncode}")
        return remote_path
