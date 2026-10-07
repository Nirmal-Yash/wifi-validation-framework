from __future__ import annotations
from dataclasses import dataclass
import os,shutil,sqlite3,sys
from pathlib import Path
@dataclass(frozen=True,slots=True)
class DoctorCheck: check_id:str;status:str;message:str
@dataclass(frozen=True,slots=True)
class DoctorReport: checks:tuple[DoctorCheck,...];ready:bool;summary:str
class RunnerDoctor:
    def __init__(self,root:str|Path): self.root=Path(root).resolve()
    def run(self,*,database:str|Path|None=None)->DoctorReport:
        checks=[DoctorCheck("python","PASS" if sys.version_info>=(3,11) else "FAIL",f"Python {sys.version.split()[0]}")]
        for tool in ("git","pytest"):
            ok=shutil.which(tool) is not None;checks.append(DoctorCheck(f"tool:{tool}","PASS" if ok else "FAIL","available" if ok else "missing from PATH"))
        for relative in ("configs","tests","lib","dashboard","scripts"):
            ok=(self.root/relative).is_dir();checks.append(DoctorCheck(f"path:{relative}","PASS" if ok else "FAIL",str(self.root/relative)))
        required=os.getenv("NETREGRESS_AUTH_REQUIRED","0").lower() not in {"0","false","no"}
        if required:
            ok=bool(os.getenv("NETREGRESS_SESSION_SECRET")) and bool(os.getenv("NETREGRESS_AUTH_USERS_JSON"));checks.append(DoctorCheck("authentication","PASS" if ok else "FAIL","configured" if ok else "enabled without required secrets/users"))
        else: checks.append(DoctorCheck("authentication","WARN","local authentication is disabled"))
        db=Path(database) if database else Path(os.getenv("NETREGRESS_DATABASE_PATH",self.root/"results"/"test_results.db"))
        if db.is_file():
            try:
                c=sqlite3.connect(db);integrity=c.execute("PRAGMA integrity_check").fetchone()[0];c.close();checks.append(DoctorCheck("database","PASS" if integrity=="ok" else "FAIL",f"integrity_check={integrity}"))
            except sqlite3.Error as exc: checks.append(DoctorCheck("database","FAIL",str(exc)))
        else: checks.append(DoctorCheck("database","WARN","database not initialized yet"))
        failures=[c for c in checks if c.status=="FAIL"];return DoctorReport(tuple(checks),not failures,"runner readiness checks passed" if not failures else f"{len(failures)} readiness check(s) failed")
