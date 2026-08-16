import os
os.environ['FLASK_TESTING']='1'; os.environ['NETFORGE_AUTH_DISABLED']='1'; os.environ['NETFORGE_ADMIN_PASSWORD']='test-password-strong'
from dashboard.enterprise_app import app
from dashboard.db import ensure_schema
from engine.execution_store import create_execution, record_metric

def test_enterprise_health():
    app.config.update(TESTING=True)
    r=app.test_client().get('/api/enterprise/health')
    assert r.status_code==200 and r.get_json()['success']

def test_operations_requires_auth_when_gate_enabled(monkeypatch):
    monkeypatch.setenv('FLASK_TESTING','0'); monkeypatch.setenv('NETFORGE_AUTH_DISABLED','0')
    client=app.test_client(); r=client.get('/operations',follow_redirects=False); assert r.status_code==302; assert '/login' in r.headers['Location']
    monkeypatch.setenv('FLASK_TESTING','1'); monkeypatch.setenv('NETFORGE_AUTH_DISABLED','1')

def test_enterprise_execution_detail_and_analytics():
    ensure_schema(); eid=create_execution('enterprise-test','unit','pytest','tier1','control-plane test','python -m pytest'); record_metric(eid,'throughput_mbps',100,'Mbps')
    client=app.test_client(); r=client.get(f'/api/enterprise/executions/{eid}'); assert r.status_code==200; p=r.get_json()['execution']; assert p['id']==eid; assert p['metrics'][0]['metric_name']=='throughput_mbps'

def test_infrastructure_adapter_boundary():
    from engine.infrastructure import adapter_for
    a=adapter_for('tier2',name='physical-lab'); assert a.preflight()['ready'] is False
    b=adapter_for('tier1',name='simulated'); assert b.preflight()['mode']=='tier1'
