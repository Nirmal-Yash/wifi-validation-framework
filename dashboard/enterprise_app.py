from __future__ import annotations
import os, json
from pathlib import Path
from functools import wraps
from flask import request, session, redirect, url_for, render_template, jsonify, send_file, abort
from dashboard.app import app as app
from dashboard.auth import authenticate, logout, current_user, can, ensure_admin, csrf_valid, ROLES
from dashboard.db import connection, ensure_schema
from engine.execution_store import get_execution, list_executions, mark_cancel_requested, record_metric, audit
from engine.orchestrator import orchestrator
from engine.regression_engine import analyze_execution
ROOT=Path(__file__).resolve().parents[1]; ARTIFACT_ROOT=ROOT/'artifacts'/'executions'
app.secret_key=os.getenv('NETFORGE_SECRET_KEY','change-me-in-production')
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.getenv('NETFORGE_COOKIE_SECURE','0')=='1')

def error(code,message,status=400,details=None): return jsonify({'success':False,'error':{'code':code,'message':message,'details':details or {}}}),status
def ok(data=None,status=200): p={'success':True}; p.update(data or {}); return jsonify(p),status
def protected(permission='view'):
    def deco(fn):
        @wraps(fn)
        def inner(*a,**kw):
            if os.getenv('NETFORGE_AUTH_DISABLED','0')=='1' and os.getenv('FLASK_TESTING','0')=='1': return fn(*a,**kw)
            if not current_user():
                if request.path.startswith('/api/'): return error('AUTH_REQUIRED','Authentication is required',401)
                return redirect(url_for('netforge_login',next=request.full_path))
            if not can(permission): return error('FORBIDDEN','Insufficient permission',403) if request.path.startswith('/api/') else abort(403)
            return fn(*a,**kw)
        return inner
    return deco

def csrf_guard():
    token=request.headers.get('X-CSRF-Token') or request.form.get('csrf')
    return csrf_valid(token)

@app.before_request
def enterprise_auth_gate():
    if request.endpoint in {'netforge_login','netforge_logout','netforge_health'} or request.path.startswith('/static/') or request.path=='/health': return None
    if os.getenv('NETFORGE_AUTH_DISABLED','0')=='1' and os.getenv('FLASK_TESTING','0')=='1': return None
    if not current_user():
        if request.path.startswith('/api/'): return error('AUTH_REQUIRED','Authentication is required',401)
        return redirect(url_for('netforge_login',next=request.full_path))
    return None

@app.route('/login',methods=['GET','POST'])
def netforge_login():
    if request.method=='GET': return render_template('login.html',bootstrap_ready=bool(os.getenv('NETFORGE_ADMIN_PASSWORD')))
    username=request.form.get('username',''); password=request.form.get('password','')
    if not username or not password: return render_template('login.html',error='Username and password are required',bootstrap_ready=bool(os.getenv('NETFORGE_ADMIN_PASSWORD'))),401
    try: ensure_admin()
    except RuntimeError as exc: return render_template('login.html',error=str(exc),bootstrap_ready=False),503
    if not authenticate(username,password): return render_template('login.html',error='Invalid credentials',bootstrap_ready=True),401
    audit('LOGIN',username,'User authenticated'); return redirect(request.args.get('next') or '/')

@app.route('/logout')
def netforge_logout():
    actor=session.get('username','unknown'); logout(); audit('LOGOUT',actor,'User logged out'); return redirect('/login')

@app.route('/operations')
def operations():
    return render_template('operations.html',user=current_user(),csrf=session.get('csrf',''))

@app.route('/analytics')
def analytics():
    return render_template('analytics.html',user=current_user(),csrf=session.get('csrf',''))

@app.route('/admin')
def admin():
    if not can('manage_users'): abort(403)
    with connection() as conn: users=[dict(r) for r in conn.execute('SELECT id,username,role,active,created_at,last_login_at FROM users ORDER BY username')]; audit_rows=[dict(r) for r in conn.execute('SELECT * FROM audit_events ORDER BY id DESC LIMIT 100')]
    return render_template('admin.html',user=current_user(),csrf=session.get('csrf',''),users=users,audit_rows=audit_rows,roles=sorted(ROLES))

@app.route('/api/enterprise/summary')
@protected()
def enterprise_summary():
    with connection() as conn:
        e=conn.execute("SELECT COUNT(*) total,SUM(CASE WHEN status='PASSED' THEN 1 ELSE 0 END) passed,SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) failed,SUM(CASE WHEN status IN ('QUEUED','RUNNING') THEN 1 ELSE 0 END) active FROM executions").fetchone()
        metrics=conn.execute('SELECT metric_name,AVG(metric_value) avg_value,MIN(metric_value) min_value,MAX(metric_value) max_value,COUNT(*) samples FROM execution_metrics GROUP BY metric_name ORDER BY metric_name').fetchall()
        regressions=conn.execute("SELECT COUNT(*) c FROM regressions WHERE created_at >= datetime('now','-7 days')").fetchone()['c']
        sites=conn.execute('SELECT COUNT(*) c FROM topologies').fetchone()['c']
    total=e['total'] or 0; passed=e['passed'] or 0
    return ok({'summary':{'executions':total,'passed':passed,'failed':e['failed'] or 0,'active':e['active'] or 0,'pass_rate':round(passed*100/total,1) if total else 0,'regressions_7d':regressions,'topologies':sites},'metrics':[dict(r) for r in metrics]})

@app.route('/api/enterprise/executions')
@protected()
def enterprise_executions():
    status=request.args.get('status'); return ok({'executions':list_executions(min(int(request.args.get('limit',100)),200),status)})

@app.route('/api/enterprise/executions/<int:eid>')
@protected()
def enterprise_execution_detail(eid):
    item=get_execution(eid)
    if not item:return error('EXECUTION_NOT_FOUND','Execution does not exist',404)
    return ok({'execution':item})

@app.route('/api/enterprise/executions',methods=['POST'])
@protected('execute')
def enterprise_create_execution():
    if not csrf_guard():return error('CSRF_INVALID','Invalid CSRF token',403)
    p=request.get_json(silent=True) or {}; args=p.get('pytest_args') or ['tests/','-m','live','-v']
    if not isinstance(args,list) or not all(isinstance(x,str) for x in args):return error('INVALID_ARGS','pytest_args must be a string array',422)
    # The API deliberately disallows arbitrary shell operators; Popen receives argv directly.
    forbidden=[';','&&','||','|','>','<','`','$(']
    if any(any(x in arg for x in forbidden) for arg in args):return error('UNSAFE_ARGS','Shell operators are not permitted',422)
    fw=str(p.get('firmware_version') or '1.0.0').strip()[:80]; suite=str(p.get('suite_name') or 'live').strip()[:120]; env=str(p.get('environment') or 'tier1').strip()[:40]
    try:eid=orchestrator.submit(fw,suite,session.get('username','api'),env,str(p.get('notes') or '')[:500],args)
    except Exception as exc:return error('EXECUTION_CREATE_FAILED',str(exc),500)
    return ok({'execution_id':eid,'status':'QUEUED'},202)

@app.route('/api/enterprise/executions/<int:eid>/cancel',methods=['POST'])
@protected('cancel')
def enterprise_cancel(eid):
    if not csrf_guard():return error('CSRF_INVALID','Invalid CSRF token',403)
    if not mark_cancel_requested(eid):return error('CANCEL_REJECTED','Execution is not cancellable',409)
    orchestrator.cancel(eid); audit('EXECUTION_CANCEL',session.get('username','unknown'),f'Execution #{eid} cancellation requested',{'execution_id':eid}); return ok({'execution_id':eid,'cancel_requested':True},202)

@app.route('/api/enterprise/executions/<int:eid>/retry',methods=['POST'])
@protected('execute')
def enterprise_retry(eid):
    if not csrf_guard():return error('CSRF_INVALID','Invalid CSRF token',403)
    old=get_execution(eid)
    if not old:return error('EXECUTION_NOT_FOUND','Execution does not exist',404)
    new=orchestrator.submit(old['firmware_version'],old.get('suite_name') or 'live',session.get('username','unknown'),old.get('environment') or 'tier1',f"Retry of execution #{eid}",None)
    audit('EXECUTION_RETRY',session.get('username','unknown'),f'Execution #{new} retried from #{eid}',{'source_execution':eid,'new_execution':new}); return ok({'execution_id':new,'source_execution_id':eid},202)

@app.route('/api/enterprise/executions/<int:eid>/analyze',methods=['POST'])
@protected('execute')
def enterprise_analyze(eid):
    if not csrf_guard():return error('CSRF_INVALID','Invalid CSRF token',403)
    try: threshold=float((request.get_json(silent=True) or {}).get('threshold_percent',10))
    except: return error('INVALID_THRESHOLD','threshold_percent must be numeric',422)
    if not 0<threshold<=100:return error('INVALID_THRESHOLD','threshold_percent must be between 0 and 100',422)
    try:return ok({'regressions':analyze_execution(eid,threshold)})
    except Exception as exc:return error('ANALYSIS_FAILED',str(exc),500)

@app.route('/api/enterprise/metrics',methods=['POST'])
@protected('execute')
def enterprise_metric():
    if not csrf_guard():return error('CSRF_INVALID','Invalid CSRF token',403)
    p=request.get_json(silent=True) or {}
    try:eid=int(p['execution_id']); value=float(p['value'])
    except (KeyError,TypeError,ValueError):return error('INVALID_METRIC','execution_id and numeric value are required',422)
    if not get_execution(eid):return error('EXECUTION_NOT_FOUND','Execution does not exist',404)
    mid=record_metric(eid,str(p.get('metric_name') or 'custom')[:120],value,str(p.get('unit') or '')[:32]); return ok({'metric_id':mid},201)

@app.route('/api/enterprise/artifacts/<int:eid>/<path:name>')
@protected('artifacts')
def enterprise_artifact(eid,name):
    with connection() as conn: row=conn.execute('SELECT path,sha256 FROM evidence WHERE execution_id=? AND path=?',(eid,name)).fetchone()
    if not row:return error('ARTIFACT_NOT_FOUND','Artifact does not exist',404)
    path=(ROOT/row['path']).resolve()
    if ROOT.resolve() not in path.parents:return error('ARTIFACT_PATH_INVALID','Invalid artifact path',400)
    if not path.exists():return error('ARTIFACT_MISSING','Artifact file is missing',410)
    return send_file(path,as_attachment=True,download_name=path.name)

@app.route('/api/enterprise/audit')
@protected('audit')
def enterprise_audit():
    with connection() as conn: rows=conn.execute('SELECT * FROM audit_events ORDER BY id DESC LIMIT 300').fetchall()
    return ok({'events':[dict(r) for r in rows]})

@app.route('/api/enterprise/users',methods=['POST'])
@protected('manage_users')
def enterprise_user_create():
    if not csrf_guard():return error('CSRF_INVALID','Invalid CSRF token',403)
    from werkzeug.security import generate_password_hash
    p=request.get_json(silent=True) or {}; username=str(p.get('username') or '').strip(); password=str(p.get('password') or ''); role=str(p.get('role') or 'viewer')
    if len(username)<3 or len(username)>80 or len(password)<12 or role not in ROLES:return error('INVALID_USER','Username/password/role validation failed',422)
    with connection() as conn:
        try: conn.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',(username,generate_password_hash(password),role)); conn.commit()
        except Exception:return error('USER_EXISTS','Username already exists',409)
    audit('USER_CREATED',session.get('username','unknown'),f'Created user {username}',{'role':role}); return ok({'username':username,'role':role},201)

@app.route('/api/enterprise/users/<int:user_id>',methods=['PATCH'])
@protected('manage_users')
def enterprise_user_update(user_id):
    if not csrf_guard():return error('CSRF_INVALID','Invalid CSRF token',403)
    p=request.get_json(silent=True) or {}; sets=[]; vals=[]
    if 'role' in p and p['role'] in ROLES:sets.append('role=?');vals.append(p['role'])
    if 'active' in p and isinstance(p['active'],bool):sets.append('active=?');vals.append(int(p['active']))
    if not sets:return error('NO_CHANGES','No valid changes supplied',422)
    vals.append(user_id)
    with connection() as conn: cur=conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?",vals); conn.commit()
    if not cur.rowcount:return error('USER_NOT_FOUND','User does not exist',404)
    audit('USER_UPDATED',session.get('username','unknown'),f'Updated user #{user_id}',p); return ok({'updated':True})

@app.route('/api/enterprise/topology/impact/<int:node_id>')
@protected()
def topology_impact(node_id):
    with connection() as conn:
        node=conn.execute('SELECT * FROM topology_nodes WHERE id=?',(node_id,)).fetchone()
        if not node:return error('NODE_NOT_FOUND','Topology node does not exist',404)
        rows=conn.execute('''SELECT n.* FROM topology_nodes n JOIN topology_links l ON (n.id=l.source_node_id OR n.id=l.target_node_id) WHERE (l.source_node_id=? OR l.target_node_id=?) AND n.id<>?''',(node_id,node_id,node_id)).fetchall()
    return ok({'node':dict(node),'neighbors':[dict(r) for r in rows]})

@app.route('/api/enterprise/health')
def netforge_health():
    ensure_schema(); return ok({'service':'netforge','status':'healthy','auth_configured':bool(os.getenv('NETFORGE_ADMIN_PASSWORD'))})

# This wrapper is the recommended WSGI entrypoint: gunicorn dashboard.enterprise_app:app
