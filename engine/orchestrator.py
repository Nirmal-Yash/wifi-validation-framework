from __future__ import annotations
import os,subprocess,threading,uuid
from pathlib import Path
from engine.execution_store import ROOT,create_execution,is_cancel_requested,mark_cancel_requested,record_artifact,record_test_results,set_status

class ExecutionOrchestrator:
    """Single-host execution manager with subprocess isolation and bounded runtime."""
    def __init__(self): self._lock=threading.RLock(); self._jobs={}; self._thread=None
    def submit(self,firmware_version='1.0.0',suite_name='live',triggered_by='api',environment='tier1',notes='',pytest_args=None):
        args=list(pytest_args or ['tests/','-m','live','-v']); command='python -m pytest '+' '.join(args); eid=create_execution(firmware_version,suite_name,triggered_by,environment,notes,command)
        thread=threading.Thread(target=self._run,args=(eid,firmware_version,args),name=f'netforge-execution-{eid}',daemon=True); thread.start(); self._thread=thread; return eid
    def cancel(self,eid):
        accepted=mark_cancel_requested(eid)
        if not accepted:return False
        with self._lock: process=self._jobs.get(eid)
        if process and process.poll() is None: process.terminate()
        return True
    def _run(self,eid,firmware_version,args):
        report_dir=ROOT/'artifacts'/'reports'; report_dir.mkdir(parents=True,exist_ok=True); junit_path=report_dir/f'execution-{eid}.xml'; log_path=report_dir/f'execution-{eid}.log'; worker_id=f'local-{os.getpid()}-{uuid.uuid4().hex[:8]}'
        command=['python','-m','pytest',*args,f'--fw-version={firmware_version}',f'--junitxml={junit_path}']
        try:
            set_status(eid,'PROVISIONING','Preparing execution worker',worker_id=worker_id,command=' '.join(command))
            if is_cancel_requested(eid): set_status(eid,'CANCELLED','Execution cancelled before start',worker_id=worker_id); return
            env=os.environ.copy(); env['NETFORGE_EXECUTION_ID']=str(eid); env['NETFORGE_LIVE_TESTS']=env.get('NETFORGE_LIVE_TESTS','1')
            timeout=float(env.get('NETFORGE_EXECUTION_TIMEOUT','3600'))
            with log_path.open('w',encoding='utf-8') as log:
                process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,text=True)
                with self._lock:self._jobs[eid]=process
                set_status(eid,'RUNNING','Pytest worker started',worker_id=worker_id)
                try:return_code=process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill(); process.wait(timeout=5)
                    set_status(eid,'ERROR',f'Execution exceeded timeout of {timeout:.0f}s',worker_id=worker_id,notes='Execution timeout')
                    return
            with self._lock:self._jobs.pop(eid,None)
            for source,kind in ((log_path,'log'),(junit_path,'json')):
                if source.exists():
                    try:record_artifact(eid,source,kind)
                    except Exception:pass
            if is_cancel_requested(eid):set_status(eid,'CANCELLED','Execution cancelled',worker_id=worker_id);return
            set_status(eid,'COLLECTING','Collecting structured test results',worker_id=worker_id); counts=record_test_results(eid,junit_path); set_status(eid,'ANALYZING','Execution results persisted',worker_id=worker_id,**counts)
            final='PASSED' if return_code==0 and counts['failed']==0 and counts['errors']==0 else 'FAILED'; set_status(eid,final,f'Execution completed with exit code {return_code}',worker_id=worker_id,**counts)
        except Exception as exc:
            with self._lock:self._jobs.pop(eid,None)
            set_status(eid,'ERROR',f'Execution worker error: {exc}',worker_id=worker_id,notes=str(exc))

orchestrator=ExecutionOrchestrator()
