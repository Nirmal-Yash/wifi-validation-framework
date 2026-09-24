from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,os,subprocess
from pathlib import Path
from typing import Any
DEFAULT_REQUIRED_PATHS=("README.md","requirements.txt","docs/CURRENT_SYSTEM_STATE.md","docs/IMPLEMENTATION_ROADMAP.md","docs/FINAL_SYSTEM_DEVELOPMENT_PLAN.md","docs/RELEASE_READINESS.md","docs/PRODUCTION_COMPLETENESS_AUDIT.md","docs/openapi.yaml","scripts/ci_release_gate.py","scripts/netregress_security_audit.py","scripts/netregress_certification.py","scripts/netregress_release.py","scripts/netregress_doctor.py")
FORBIDDEN_TRACKED_SUFFIXES=(".db",".pcap",".log",".tmp",".pyc")
FORBIDDEN_TRACKED_NAMES={".env",".env.local",".env.production"}
@dataclass(frozen=True,slots=True)
class ReleaseAudit:
    branch:str;commit:str;tree:str;clean:bool;required_paths_present:bool;forbidden_tracked_files:tuple[str,...];syntax_errors:tuple[str,...];release_ready:bool
class ReleaseManifestService:
    def __init__(self,root:str|Path): self.root=Path(root).resolve()
    def _git(self,*args:str)->str:
        result=subprocess.run(["git",*args],cwd=self.root,capture_output=True,text=True,check=False,timeout=10)
        if result.returncode!=0: raise RuntimeError(result.stderr.strip() or "git command failed")
        return result.stdout.strip()
    def tracked_files(self)->tuple[str,...]:
        result=subprocess.run(["git","ls-files","-z"],cwd=self.root,capture_output=True,check=False,timeout=10)
        if result.returncode!=0: raise RuntimeError("unable to enumerate tracked files")
        return tuple(x for x in result.stdout.decode().split("\0") if x)
    def audit(self)->ReleaseAudit:
        branch=self._git("branch","--show-current") or os.getenv("GITHUB_REF_NAME","")
        commit=self._git("rev-parse","HEAD");tree=self._git("rev-parse","HEAD^{tree}")
        clean=not self._git("status","--porcelain");tracked=self.tracked_files()
        forbidden=tuple(sorted(p for p in tracked if Path(p).name in FORBIDDEN_TRACKED_NAMES or Path(p).suffix.lower() in FORBIDDEN_TRACKED_SUFFIXES or p.startswith(("results/","artifacts/",".robust-backups/"))))
        required=all((self.root/p).is_file() for p in DEFAULT_REQUIRED_PATHS);errors=[]
        for p in tracked:
            if p.endswith(".py"):
                try: compile((self.root/p).read_text(encoding="utf-8"),p,"exec")
                except (OSError,SyntaxError) as exc: errors.append(f"{p}: {exc}")
        ready=branch=="main" and clean and required and not forbidden and not errors
        return ReleaseAudit(branch,commit,tree,clean,required,forbidden,tuple(sorted(errors)),ready)
    def manifest(self,*,audit:ReleaseAudit|None=None)->dict[str,Any]:
        audit=audit or self.audit();current=self.root/"docs/CURRENT_SYSTEM_STATE.md";roadmap=self.root/"docs/IMPLEMENTATION_ROADMAP.md";files=[]
        for p in self.tracked_files():
            path=self.root/p
            if not path.is_file(): continue
            data=path.read_bytes();files.append({"path":p,"size_bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})
        return {"schema_version":"netregress-release-manifest.v1","generated_at":datetime.now(timezone.utc).isoformat(),"release_track":"standalone-runner","branch":audit.branch,"commit":audit.commit,"tree":audit.tree,"working_tree_clean":audit.clean,"required_paths_present":audit.required_paths_present,"forbidden_tracked_files":list(audit.forbidden_tracked_files),"syntax_errors":list(audit.syntax_errors),"release_ready":audit.release_ready,"system_state_sha256":hashlib.sha256(current.read_bytes()).hexdigest() if current.is_file() else None,"roadmap_sha256":hashlib.sha256(roadmap.read_bytes()).hexdigest() if roadmap.is_file() else None,"tracked_file_count":len(files),"files":files}
    def write_manifest(self,output:str|Path)->Path:
        destination=Path(output)
        if not destination.is_absolute(): destination=self.root/destination
        destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(self.manifest(),indent=2,sort_keys=True)+"\n",encoding="utf-8");return destination
