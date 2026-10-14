from __future__ import annotations
from dataclasses import dataclass
import os,signal,subprocess,sys
from pathlib import Path

@dataclass(frozen=True,slots=True)
class RunProcessHandle:
    pid:int
    command:tuple[str,...]

class RunProcessManager:
    def __init__(self,root:str|Path): self.root=Path(root).resolve()
    def start(self,*,tests:tuple[str,...]|None=None,firmware_version:str="v1.0",env:dict[str,str]|None=None)->RunProcessHandle:
        command=[sys.executable,"-m","pytest"]
        if tests: command.extend(tests)
        command.extend(["-v",f"--firmware-version={firmware_version}"])
        child_env=os.environ.copy();child_env.update(env or {})
        process=subprocess.Popen(command,cwd=self.root,env=child_env,start_new_session=True)
        return RunProcessHandle(process.pid,tuple(command))
    def cancel(self,pid:int)->None:
        os.killpg(os.getpgid(pid),signal.SIGTERM)
    def kill(self,pid:int)->None:
        os.killpg(os.getpgid(pid),signal.SIGKILL)
