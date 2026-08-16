from __future__ import annotations
import hashlib,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from db.init_db import DB_PATH,initialize
from db.migrations import migrate
ROOT=Path(__file__).resolve().parents[1]; ARTIFACT_ROOT=ROOT/'artifacts'/'executions'
def _now(): return datetime.now(timezone.utc).isoformat()
def connect():
    initialize(DB_PATH); conn=sqlite3.connect(DB_PATH,timeout=10); conn.row_factory=sqlite3.Row; conn.execute('PRAGMA foreign_keys=ON'); conn.execute('PRAGMA busy_timeout=10000'); migrate(conn); return conn
def audit(event_type,actor,message,payload=None):
    with connect() as conn: conn.execute('INSERT INTO audit_events(event_type,actor,message,payload_json) VALUES(?,?,?,?)',(event_type,actor or 'system',message,json.dumps(payload or {},sort_keys=True))); conn.commit()
def topology_snapshot():
    path=ROOT/'config'/'devices.yaml'; content=path.read_text(encoding='utf-8') if path.exists() else None; digest=hashlib.sha256(content.encode('utf-8')).hexdigest() if content is not None else None
    with connect() as conn: row=conn.execute("SELECT tv.id,tv.version FROM topology_versions tv JOIN topologies t ON t.id=tv.topology_id WHERE tv.status='ACTIVE' ORDER BY tv.id DESC LIMIT 1").fetchone()
    return digest,(row['id'] if row else None),content
def ensure_firmware(conn,version): conn.execute('INSERT OR IGNORE INTO firmware_metadata(firmware_version) VALUES (?)',(version,))
def create_execution(firmware_version='1.0.0',suite_name='live',triggered_by='api',environment='tier1',notes='',command=''):
    topology_hash,topology_version_id,snapshot=topology_snapshot()
    with connect() as conn:
        ensure_firmware(conn,firmware_version); cur=conn.execute('''INSERT INTO executions(firmware_version,topology_version_id,mode,status,suite_name,triggered_by,environment,notes,topology_hash,topology_snapshot,command,phase) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(firmware_version,topology_version_id,environment,'QUEUED',suite_name,triggered_by,environment,notes,topology_hash,snapshot,command,'QUEUED')); eid=int(cur.lastrowid); add_event(conn,eid,'QUEUED','Execution queued',{'actor':triggered_by}); conn.commit()
    audit('EXECUTION_CREATED',triggered_by,f'Execution #{eid} queued',{'execution_id':eid,'firmware':firmware_version,'environment':environment}); return eid
def add_event(conn,eid,event_type,message,payload=None): conn.execute('INSERT INTO execution_events(execution_id,event_type,message,payload_json) VALUES(?,?,?,?)',(eid,event_type,message,json.dumps(payload or {},sort_keys=True)))
def set_status(eid,status,message=None,**fields):
    allowed={'QUEUED','PROVISIONING','RUNNING','COLLECTING','ANALYZING','PASSED','FAILED','ERROR','CANCELLED'}
    if status not in allowed: raise ValueError(f'Unsupported execution status: {status}')
    db_status='RUNNING' if status in {'PROVISIONING','COLLECTING','ANALYZING'} else status; assignments=['status=?','phase=?']; values=[db_status,status]
    if db_status=='RUNNING': assignments.append('started_at=COALESCE(started_at,CURRENT_TIMESTAMP)')
    if db_status in {'PASSED','FAILED','ERROR','CANCELLED'}: assignments.append('finished_at=CURRENT_TIMESTAMP')
    for key in ('worker_id','command','notes','total_tests','passed','failed','blocked','skipped','errors'):
        if key in fields: assignments.append(f'{key}=?'); values.append(fields[key])
    values.append(eid)
    with connect() as conn: conn.execute(f'UPDATE executions SET {", ".join(assignments)} WHERE id=?',values); add_event(conn,eid,status,message or status,fields); conn.commit()
    audit('EXECUTION_STATE','system',message or status,{'execution_id':eid,'status':status})
def mark_cancel_requested(eid):
    with connect() as conn:
        cur=conn.execute("UPDATE executions SET cancel_requested=1 WHERE id=? AND status IN ('QUEUED','RUNNING') AND cancel_requested=0",(eid,));
        if cur.rowcount: add_event(conn,eid,'CANCEL_REQUESTED','Cancellation requested')
        conn.commit(); return cur.rowcount==1
def is_cancel_requested(eid):
    with connect() as conn: row=conn.execute('SELECT cancel_requested FROM executions WHERE id=?',(eid,)).fetchone()
    return bool(row and row['cancel_requested'])
def get_execution(eid):
    with connect() as conn:
        row=conn.execute('SELECT * FROM executions WHERE id=?',(eid,)).fetchone()
        if not row:return None
        result=dict(row); result['results']=[dict(r) for r in conn.execute('SELECT * FROM test_results WHERE execution_id=? ORDER BY id',(eid,))]; result['metrics']=[dict(r) for r in conn.execute('SELECT * FROM execution_metrics WHERE execution_id=? ORDER BY id',(eid,))]; result['events']=[dict(r) for r in conn.execute('SELECT * FROM execution_events WHERE execution_id=? ORDER BY id',(eid,))]; result['artifacts']=[dict(r) for r in conn.execute('SELECT * FROM evidence WHERE execution_id=? ORDER BY id',(eid,))]; return result
def list_executions(limit=50,status=None):
    limit=max(1,min(int(limit),200))
    with connect() as conn: rows=conn.execute('SELECT * FROM executions WHERE status=? ORDER BY id DESC LIMIT ?',(status,limit)).fetchall() if status else conn.execute('SELECT * FROM executions ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
    return [dict(r) for r in rows]
def record_artifact(eid,source,kind,test_result_id=None):
    source=Path(source)
    if not source.exists() or not source.is_file(): raise FileNotFoundError(source)
    target_dir=ARTIFACT_ROOT/str(eid); target_dir.mkdir(parents=True,exist_ok=True); target=target_dir/(source.name.replace('..','_').replace('/','_').replace('\\','_')); target.write_bytes(source.read_bytes()); digest=hashlib.sha256(target.read_bytes()).hexdigest(); rel=target.relative_to(ROOT).as_posix()
    with connect() as conn: cur=conn.execute('INSERT INTO evidence(execution_id,test_result_id,kind,path,sha256) VALUES(?,?,?,?,?)',(eid,test_result_id,kind,rel,digest)); conn.commit(); return {'id':cur.lastrowid,'execution_id':eid,'kind':kind,'path':rel,'sha256':digest}
def record_metric(eid,metric_name,metric_value,metric_unit='',test_result_id=None):
    with connect() as conn:
        cur=conn.execute('INSERT INTO execution_metrics(execution_id,test_result_id,metric_name,metric_value,metric_unit) VALUES(?,?,?,?,?)',(eid,test_result_id,metric_name,float(metric_value),metric_unit)); conn.commit(); return int(cur.lastrowid)
def record_test_results(eid,junit_path):
    import xml.etree.ElementTree as ET
    if not Path(junit_path).exists(): return {'total':0,'passed':0,'failed':0,'blocked':0,'skipped':0,'errors':0}
    root=ET.parse(junit_path).getroot(); cases=root.findall('.//testcase'); counts={'total':0,'passed':0,'failed':0,'blocked':0,'skipped':0,'errors':0}
    with connect() as conn:
        conn.execute('DELETE FROM test_results WHERE execution_id=?',(eid,))
        for case in cases:
            counts['total']+=1; failure,error,skipped=case.find('failure'),case.find('error'),case.find('skipped')
            if failure is not None: status,bucket,message='FAILED','failed',failure.get('message') or (failure.text or '')
            elif error is not None: status,bucket,message='ERROR','errors',error.get('message') or (error.text or '')
            elif skipped is not None: status,bucket,message='SKIPPED','skipped',skipped.get('message') or ''
            else: status,bucket,message='PASSED','passed',''
            counts[bucket]+=1; duration=float(case.get('time') or 0); conn.execute('INSERT INTO test_results(execution_id,test_name,test_file,status,duration,duration_ms,error_message,failure_phase) VALUES(?,?,?,?,?,?,?,?)',(eid,case.get('name') or 'unknown',case.get('classname') or '',status,duration,duration*1000,message,''))
        conn.execute('UPDATE executions SET total_tests=?,passed=?,failed=?,blocked=?,skipped=?,errors=? WHERE id=?',(counts['total'],counts['passed'],counts['failed'],counts['blocked'],counts['skipped'],counts['errors'],eid)); conn.commit()
    return counts
