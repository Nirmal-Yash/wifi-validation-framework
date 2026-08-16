from __future__ import annotations
import os,secrets
from functools import wraps
from flask import abort,session
from werkzeug.security import check_password_hash,generate_password_hash
from dashboard.db import connection

ROLES={'admin':{'view','execute','cancel','topology_edit','topology_commit','manage_users','audit','artifacts','settings'},'operator':{'view','execute','cancel','topology_edit','artifacts','audit'},'viewer':{'view','artifacts'}}

def ensure_admin():
    username=os.getenv('NETFORGE_ADMIN_USER','admin').strip(); password=os.getenv('NETFORGE_ADMIN_PASSWORD','').strip()
    if not password:return False
    with connection() as conn:
        row=conn.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()
        if row:return True
        conn.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',(username,generate_password_hash(password),'admin')); conn.commit()
    return True

def authenticate(username,password):
    with connection() as conn: row=conn.execute('SELECT * FROM users WHERE username=? AND active=1',(username.strip(),)).fetchone()
    if not row or not check_password_hash(row['password_hash'],password):return None
    session.clear(); session['user_id']=row['id']; session['username']=row['username']; session['role']=row['role']; session['csrf']=secrets.token_urlsafe(24)
    with connection() as conn: conn.execute('UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?',(row['id'],)); conn.commit()
    return dict(row)

def logout(): session.clear()
def current_user(): return {'id':session.get('user_id'),'username':session.get('username'),'role':session.get('role')} if session.get('user_id') else None
def can(permission): return session.get('role') in ROLES and permission in ROLES[session['role']]
def login_required(permission='view'):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            if os.getenv('NETFORGE_AUTH_DISABLED','0')=='1' and os.getenv('FLASK_TESTING','0')=='1':return fn(*args,**kwargs)
            if not current_user(): abort(401)
            if not can(permission): abort(403)
            return fn(*args,**kwargs)
        return wrapped
    return decorator
def csrf_valid(token): return bool(token) and secrets.compare_digest(token,session.get('csrf',''))
def bootstrap_required():
    if not ensure_admin():
        raise RuntimeError('NETFORGE_ADMIN_PASSWORD is required before authentication can be enabled')
