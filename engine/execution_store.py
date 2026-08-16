from __future__ import annotations
import hashlib, json, os, sqlite3, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DB_PATH=ROOT/'db/results.db'
ARTIFACT_ROOT=ROOT/'artifacts/executions'
def connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=10); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA busy_timeout=10000'); return c
def ensure_schema():
    from db.init_db import initialize
    initialize(DB_PATH)
def create_execution(suite,environment,runner,tier,command,working_directory='',topology_version=None,topology_hash=None,topology_snapshot=None):
    ensure_schema()
    with connect() as conn:
        cur=conn.execute('INSERT INTO executions(suite,environment,runner,tier,command,working_directory,status,started_at,topology_version,topology_hash,topology_snapshot) VALUES(?,?,?,?,?,?,?,datetime(\'now\'),?,?,?)',(suite,environment,runner,tier,command,working_directory,'QUEUED',topology_version,topology_hash,topology_snapshot))
        conn.commit(); return int(cur.lastrowid)
def update_execution(eid,**fields):
    allowed={'status','started_at','finished_at','exit_code','error_message','result_summary','worker_pid','topology_version','topology_hash','topology_snapshot'}
    fields={k:v for k,v in fields.items() if k in allowed}
    if not fields:return
    sql='UPDATE executions SET '+','.join(f'{k}=?' for k in fields)+' WHERE id=?'
    with connect() as conn: conn.execute(sql,(*fields.values(),eid)); conn.commit()
def record_event(eid,event_type,payload=None):
    with connect() as conn: conn.execute('INSERT INTO execution_events(execution_id,event_type,payload,created_at) VALUES(?,?,?,datetime(\'now\'))',(eid,event_type,json.dumps(payload or {},sort_keys=True))); conn.commit()
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
            elif skipped is not None: status,bucket,message='SKIPPED','skipped',skipped.get('message') or (skipped.text or '')
            else: status,bucket,message='PASSED','passed',''
            counts[bucket]+=1; conn.execute('INSERT INTO test_results(execution_id,test_name,status,message,duration_seconds) VALUES(?,?,?,?,?)',(eid,case.get('name','unknown'),status,message,float(case.get('time') or 0)))
        conn.commit()
    return counts
def record_metric_from_process(eid,name,cmd,unit='seconds'):
    start=time.monotonic(); p=subprocess.run(cmd,check=False,capture_output=True,text=True); record_metric(eid,name,time.monotonic()-start,unit); return p
def summarize(eid):
    row=get_execution(eid) or {}; results=row.get('results',[]); metrics=row.get('metrics',[]); return {'execution_id':eid,'status':row.get('status'),'total':len(results),'passed':sum(r['status']=='PASSED' for r in results),'failed':sum(r['status']=='FAILED' for r in results),'errors':sum(r['status']=='ERROR' for r in results),'skipped':sum(r['status']=='SKIPPED' for r in results),'metrics':metrics}
