from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import shlex
from .command_runner import CommandRunner,CommandResult
class LabControllerError(RuntimeError): pass
@dataclass(frozen=True,slots=True)
class LabOperationResult: operation:str; result:CommandResult
class LabController:
    def __init__(self,*,command_runner,provisioning_script,lab_id): self.command_runner=command_runner; self.provisioning_script=Path(provisioning_script).resolve(); self.lab_id=lab_id
    def validate_launcher(self):
        if not self.provisioning_script.is_file(): raise LabControllerError(f"provisioning script not found: {self.provisioning_script}")
        if not self.provisioning_script.stat().st_mode & 0o111: raise LabControllerError("provisioning launcher is not executable")
    def provision(self,*args): return self._run("provision",*args)
    def cleanup(self,*args): return self._run("cleanup",*args)
    def _run(self,operation,*args):
        self.validate_launcher(); command=" ".join(shlex.quote(x) for x in ("bash",str(self.provisioning_script),*args))
        result=self.command_runner.execute_shell("local-lab",command,command_category=f"lab_{operation}",idempotent=False,display_command=f"bash {self.provisioning_script.name} {' '.join(args)}".strip())
        if result.transport_error or result.timed_out: raise LabControllerError(result.transport_error or "lab operation timeout")
        if result.exit_code not in (None,0): raise LabControllerError(f"lab {operation} failed with exit code {result.exit_code}")
        return LabOperationResult(operation,result)
