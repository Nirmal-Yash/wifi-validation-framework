from __future__ import annotations
import json, os
from pathlib import Path
import yaml
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename
from dashboard.db import ROOT, connection, ensure_schema
try:
    from engine.topology_importer import TopologyImporter
except ImportError: TopologyImporter=None
try:
    from gns3fy import Gns3Connector, Project
except ImportError: Gns3Connector=Project=None
TEMPLATE_DIR=ROOT/'dashboard'/'templates'; UPLOAD_DIR=ROOT/'artifacts'/'uploads'; CONFIG_DIR=ROOT/'config'
app=Flask(__name__,template_folder=str(TEMPLATE_DIR)); app.config.update(UPLOAD_FOLDER=str(UPLOAD_DIR),MAX_CONTENT_LENGTH=16*1024*1024)
UPLOAD_DIR.mkdir(parents=True,exist_ok=True); CONFIG_DIR.mkdir(parents=True,exist_ok=True)
def api_error(code,message,status=400,details=None): return jsonify({'success':False,'error':{'code':code,'message':message,'details':details or {}}}),status
def api_ok(data=None,status=200): payload={'success':True}; payload.update(data or {}); return jsonify(payload),status
def load_yaml_topology():
    path=CONFIG_DIR/'devices.yaml'
    if not path.exists(): return {'nodes':{},'target_environment':{}}
    try:
        data=yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        if not isinstance(data,dict): raise ValueError('devices.yaml root must be an object')
        return data
    except (OSError,yaml.YAMLError,ValueError) as exc: raise RuntimeError(f'Invalid topology configuration: {exc}') from exc
def infer_type(name):
    value=str(name).lower()
    for needle,kind in (('router','router'),('switch','switch'),('ap','access_point'),('wifi','access_point'),('pc','client'),('client','client'),('monitor','monitor')):
        if needle in value:return kind
    return 'generic'
def ensure_topology_seed():
    with connection() as conn:
        if conn.execute('SELECT COUNT(*) c FROM topologies').fetchone()['c']:return
        nodes=load_yaml_topology().get('nodes',{})
        if not nodes:return
        conn.execute('INSERT INTO topologies(name,description,source) VALUES(?,?,?)',('default','Imported from config/devices.yaml','local')); tid=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.execute('INSERT INTO topology_versions(topology_id,version,status) VALUES(?,?,?)',(tid,1,'ACTIVE')); vid=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        for key,details in nodes.items():
            details=details or {}; conn.execute('INSERT INTO topology_nodes(topology_version_id,node_key,name,node_type,namespace,interface_name,config_path,x,y,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)',(vid,key,key,infer_type(key),details.get('namespace'),details.get('interface'),details.get('config_path'),details.get('x',0),details.get('y',0),json.dumps(details)))
        conn.commit()
def topology_payload(version_id=None):
    ensure_topology_seed()
    with connection() as conn:
        version=conn.execute('SELECT tv.id,tv.topology_id,t.name,tv.version,tv.status,tv.created_at FROM topology_versions tv JOIN topologies t ON t.id=tv.topology_id WHERE '+('tv.id=?' if version_id is not None else "tv.status='ACTIVE'")+' ORDER BY tv.id DESC LIMIT 1',((version_id,) if version_id is not None else ())).fetchone()
        if not version:return {'nodes':[],'edges':[],'topology':None}
        rows=conn.execute('SELECT * FROM topology_nodes WHERE topology_version_id=? ORDER BY id',(version['id'],)).fetchall(); links=conn.execute('SELECT * FROM topology_links WHERE topology_version_id=? ORDER BY id',(version['id'],)).fetchall()
        icons={'access_point':'\\uf1eb','client':'\\uf109','router':'\\uf0e8','switch':'\\uf6ff','monitor':'\\uf21b','generic':'\\uf233'}
        nodes=[{'id':r['id'],'node_key':r['node_key'],'label':r['name'],'type':r['node_type'],'namespace':r['namespace'],'interface':r['interface_name'],'x':r['x'],'y':r['y'],'shape':'icon','title':f"Device: {r['name']}\\nType: {r['node_type']}\\nNamespace: {r['namespace'] or 'N/A'}\\nInterface: {r['interface_name'] or 'N/A'}",'icon':{'face':'Font Awesome 6 Free','code':icons.get(r['node_type'],icons['generic']),'weight':900,'size':48}} for r in rows]
        edges=[{'id':r['id'],'from':r['source_node_id'],'to':r['target_node_id'],'width':2,'smooth':{'type':'dynamic'}} for r in links]
        return {'nodes':nodes,'edges':edges,'topology':{'id':version['topology_id'],'name':version['name'],'version_id':version['id'],'version':version['version'],'status':version['status'],'created_at':version['created_at']}}
def topology_rows(conn,version_id):
    rows=conn.execute('SELECT * FROM topology_nodes WHERE topology_version_id=? ORDER BY id',(version_id,)).fetchall(); links=conn.execute('SELECT * FROM topology_links WHERE topology_version_id=? ORDER BY id',(version_id,)).fetchall(); return rows,links
def write_topology_version(conn,version_id,nodes,edges):
    if not isinstance(nodes,list) or not isinstance(edges,list): raise ValueError('nodes and edges must be arrays')
    if not nodes: raise ValueError('topology must contain at least one device')
    keys=set(); id_map={}
    for i,node in enumerate(nodes,1):
        key=str(node.get('node_key') or node.get('id') or f'node_{i}'); name=str(node.get('label') or node.get('name') or key).strip()
        if key in keys: raise ValueError(f'duplicate node key: {key}')
        keys.add(key); cur=conn.execute('INSERT INTO topology_nodes(topology_version_id,node_key,name,node_type,namespace,interface_name,config_path,x,y,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)',(version_id,key,name,str(node.get('type') or infer_type(name)),node.get('namespace'),node.get('interface'),node.get('config_path'),float(node.get('x',0)),float(node.get('y',0)),json.dumps(node))); id_map[node.get('id',i)]=cur.lastrowid
    for edge in edges:
        a,b=id_map.get(edge.get('from')),id_map.get(edge.get('to'))
        if not a or not b or a==b: raise ValueError('invalid topology link')
        conn.execute('INSERT INTO topology_links(topology_version_id,source_node_id,target_node_id,source_interface,target_interface,metadata_json) VALUES(?,?,?,?,?,?)',(version_id,a,b,edge.get('source_interface'),edge.get('target_interface'),json.dumps(edge)))
def persist_topology(name,nodes,edges,source='local'):
    with connection() as conn:
        existing=conn.execute('SELECT id FROM topologies WHERE name=?',(str(name or 'default').strip()[:100] or 'default',)).fetchone(); name=str(name or 'default').strip()[:100] or 'default'
        if existing: tid=existing['id']; version=conn.execute('SELECT COALESCE(MAX(version),0)+1 v FROM topology_versions WHERE topology_id=?',(tid,)).fetchone()['v']
        else: conn.execute('INSERT INTO topologies(name,source) VALUES(?,?)',(name,source)); tid=conn.execute('SELECT last_insert_rowid()').fetchone()[0]; version=1
        conn.execute('INSERT INTO topology_versions(topology_id,version,status) VALUES(?,?,?)',(tid,version,'ACTIVE')); vid=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        try: write_topology_version(conn,vid,nodes,edges)
        except Exception: conn.execute('DELETE FROM topology_versions WHERE id=?',(vid,)); raise
        conn.execute("UPDATE topology_versions SET status='ARCHIVED' WHERE topology_id=? AND id<>? AND status='ACTIVE'",(tid,vid)); conn.execute('UPDATE topologies SET updated_at=CURRENT_TIMESTAMP WHERE id=?',(tid,)); conn.commit()
    return {'topology_id':tid,'version_id':vid,'version':version,'name':name,'source':source}
def create_draft(topology_id,nodes=None,edges=None):
    with connection() as conn:
        top=conn.execute('SELECT * FROM topologies WHERE id=?',(topology_id,)).fetchone()
        if not top: raise LookupError('Topology does not exist')
        source=conn.execute("SELECT * FROM topology_versions WHERE topology_id=? AND status='DRAFT' ORDER BY id DESC LIMIT 1",(topology_id,)).fetchone()
        if source:return {'id':source['id'],'version':source['version'],'status':'DRAFT'}
        base=conn.execute('SELECT id,version FROM topology_versions WHERE topology_id=? ORDER BY version DESC LIMIT 1',(topology_id,)).fetchone(); version=(base['version'] if base else 0)+1
        conn.execute('INSERT INTO topology_versions(topology_id,version,status) VALUES(?,?,?)',(topology_id,version,'DRAFT')); vid=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        if nodes is None:
            if not base: raise ValueError('Topology has no base version')
            rows,links=topology_rows(conn,base['id']); idmap={}
            for r in rows:
                cur=conn.execute('INSERT INTO topology_nodes(topology_version_id,node_key,name,node_type,namespace,interface_name,config_path,x,y,metadata_json) SELECT ?,node_key,name,node_type,namespace,interface_name,config_path,x,y,metadata_json FROM topology_nodes WHERE id=?',(vid,r['id'])); idmap[r['id']]=cur.lastrowid
            for e in links: conn.execute('INSERT INTO topology_links(topology_version_id,source_node_id,target_node_id,source_interface,target_interface,enabled,metadata_json) VALUES(?,?,?,?,?,?,?)',(vid,idmap[e['source_node_id']],idmap[e['target_node_id']],e['source_interface'],e['target_interface'],e['enabled'],e['metadata_json']))
        else: write_topology_version(conn,vid,nodes,edges or [])
        conn.commit(); return {'id':vid,'version':version,'status':'DRAFT'}
def replace_draft(version_id,nodes,edges):
    with connection() as conn:
        v=conn.execute('SELECT * FROM topology_versions WHERE id=?',(version_id,)).fetchone()
        if not v or v['status']!='DRAFT': raise ValueError('Only a DRAFT topology version can be edited')
        conn.execute('DELETE FROM topology_links WHERE topology_version_id=?',(version_id,)); conn.execute('DELETE FROM topology_nodes WHERE topology_version_id=?',(version_id,)); write_topology_version(conn,version_id,nodes,edges); conn.execute("UPDATE topology_versions SET status='VALIDATED' WHERE id=?",(version_id,)); conn.commit(); return {'valid':True,'version':dict(v)}
def commit_draft(version_id):
    with connection() as conn:
        v=conn.execute('SELECT * FROM topology_versions WHERE id=?',(version_id,)).fetchone()
        if not v or v['status'] not in ('DRAFT','VALIDATED'): raise ValueError('Draft does not exist or is not editable')
        count=conn.execute('SELECT COUNT(*) c FROM topology_nodes WHERE topology_version_id=?',(version_id,)).fetchone()['c']
        if not count: raise ValueError('Cannot commit an empty topology')
        conn.execute("UPDATE topology_versions SET status='ARCHIVED' WHERE topology_id=? AND status='ACTIVE'",(v['topology_id'],)); conn.execute("UPDATE topology_versions SET status='ACTIVE' WHERE id=?",(version_id,)); conn.execute('UPDATE topologies SET updated_at=CURRENT_TIMESTAMP WHERE id=?',(v['topology_id'],)); conn.commit(); return {'version':dict(conn.execute('SELECT * FROM topology_versions WHERE id=?',(version_id,)).fetchone())}
@app.before_request
def bootstrap(): ensure_schema()
@app.errorhandler(HTTPException)
def http_error(exc):
    if request.path.startswith('/api/'):return api_error(exc.name.upper().replace(' ','_'),exc.description,exc.code)
    return render_template('error.html',code=exc.code,name=exc.name,message=exc.description),exc.code
@app.errorhandler(Exception)
def unhandled_error(exc):
    app.logger.exception('Unhandled request error')
    if request.path.startswith('/api/'):return api_error('INTERNAL_ERROR','Unexpected server error. Check the dashboard log for the exception.',500)
    return render_template('error.html',code=500,name='Internal Server Error',message='The request could not be completed.'),500
@app.route('/')
def index():
    with connection() as conn:
        total=conn.execute('SELECT COUNT(*) c FROM test_logs').fetchone()['c']; passed=conn.execute("SELECT COUNT(*) c FROM test_logs WHERE status='PASSED'").fetchone()['c']; failures=conn.execute("SELECT firmware_version,test_name,error_message,timestamp FROM test_logs WHERE status IN ('FAILED','ERROR') ORDER BY timestamp DESC LIMIT 5").fetchall()
    return render_template('dashboard.html',total=total,passed=passed,failed=total-passed,rate=round(passed/total*100,1) if total else 0,failures=failures)
@app.route('/health')
def health():
    with connection() as conn:
        conn.execute('SELECT 1').fetchone(); metrics={ 'topologies':conn.execute('SELECT COUNT(*) c FROM topologies').fetchone()['c'],'executions':conn.execute('SELECT COUNT(*) c FROM executions').fetchone()['c'],'test_logs':conn.execute('SELECT COUNT(*) c FROM test_logs').fetchone()['c'] }
    return api_ok({'service':'dashboard','database':'ok','metrics':metrics})
@app.route('/topology')
def topology():return render_template('topology_enhanced.html')
@app.route('/history')
def history():
    with connection() as conn:
        fw_list=conn.execute('SELECT firmware_version,MAX(timestamp) latest FROM test_logs GROUP BY firmware_version ORDER BY latest DESC').fetchall(); values=[r['firmware_version'] for r in fw_list]; fw_a=request.args.get('fw_a') or (values[-1] if values else ''); fw_b=request.args.get('fw_b') or (values[0] if values else fw_a); comparisons=[]
        if fw_a and fw_b: comparisons=[dict(r) for r in conn.execute('SELECT test_name,MAX(CASE WHEN firmware_version=? THEN status END) status_a,MAX(CASE WHEN firmware_version=? THEN status END) status_b FROM test_logs WHERE firmware_version IN (?,?) GROUP BY test_name ORDER BY test_name',(fw_a,fw_b,fw_a,fw_b)).fetchall()]
        logs=conn.execute('SELECT * FROM test_logs ORDER BY timestamp DESC LIMIT 200').fetchall(); counts=conn.execute("SELECT SUM(CASE WHEN status='PASSED' THEN 1 ELSE 0 END) passed,SUM(CASE WHEN status IN ('FAILED','ERROR') THEN 1 ELSE 0 END) failed,SUM(CASE WHEN status NOT IN ('PASSED','FAILED','ERROR') THEN 1 ELSE 0 END) other,COUNT(*) total FROM test_logs").fetchone()
    return render_template('history_enhanced.html',logs=logs,fw_list=fw_list,fw_a=fw_a,fw_b=fw_b,comparisons=comparisons,counts=dict(counts))
@app.route('/about')
def about():return render_template('about_enhanced.html')
@app.route('/api/topology_data')
def topology_data():return api_ok(topology_payload())
@app.route('/api/topologies')
def list_topologies():
    with connection() as conn: rows=conn.execute('SELECT t.id,t.name,t.description,t.source,COUNT(tv.id) version_count,MAX(tv.version) latest_version FROM topologies t LEFT JOIN topology_versions tv ON tv.topology_id=t.id GROUP BY t.id ORDER BY t.id DESC').fetchall()
    return api_ok({'topologies':[dict(r) for r in rows]})
@app.route('/api/topologies/<int:topology_id>/versions')
def topology_versions(topology_id):
    with connection() as conn:
        topology=conn.execute('SELECT * FROM topologies WHERE id=?',(topology_id,)).fetchone()
        if not topology:return api_error('TOPOLOGY_NOT_FOUND','Topology does not exist',404)
        rows=conn.execute('SELECT id,version,status,created_at FROM topology_versions WHERE topology_id=? ORDER BY version DESC',(topology_id,)).fetchall()
    return api_ok({'topology':dict(topology),'versions':[dict(r) for r in rows]})
@app.route('/api/topologies/<int:topology_id>/versions/<int:version_id>')
def get_topology_version(topology_id,version_id):
    with connection() as conn:
        if not conn.execute('SELECT id FROM topology_versions WHERE id=? AND topology_id=?',(version_id,topology_id)).fetchone():return api_error('TOPOLOGY_VERSION_NOT_FOUND','Topology version does not exist',404)
    return api_ok(topology_payload(version_id))
@app.route('/api/topology/validate',methods=['POST'])
def validate_topology():
    p=request.get_json(silent=True) or {}; nodes,links=p.get('nodes',[]),p.get('edges',[])
    if not isinstance(nodes,list) or not isinstance(links,list):return api_error('INVALID_TOPOLOGY','nodes and edges must be arrays',422)
    ids={n.get('id') for n in nodes}; bad=[e for e in links if e.get('from') not in ids or e.get('to') not in ids]
    if not nodes:return api_error('EMPTY_TOPOLOGY','Topology must contain at least one device',422)
    if bad:return api_error('INVALID_LINK','One or more links reference missing nodes',422,{'count':len(bad)})
    return api_ok({'valid':True,'node_count':len(nodes),'link_count':len(links)})
@app.route('/api/topologies/<int:topology_id>/draft',methods=['POST'])
def draft_create(topology_id):
    try:return api_ok({'version':create_draft(topology_id,(request.get_json(silent=True) or {}).get('nodes'),(request.get_json(silent=True) or {}).get('edges'))},201)
    except LookupError as e:return api_error('TOPOLOGY_NOT_FOUND',str(e),404)
    except (ValueError,TypeError) as e:return api_error('DRAFT_INVALID',str(e),422)
@app.route('/api/topologies/<int:topology_id>/drafts/<int:version_id>',methods=['PUT'])
def draft_update(topology_id,version_id):
    p=request.get_json(silent=True) or {}
    try:
        with connection() as conn:
            if not conn.execute('SELECT id FROM topology_versions WHERE id=? AND topology_id=?',(version_id,topology_id)).fetchone():return api_error('TOPOLOGY_VERSION_NOT_FOUND','Topology version does not exist',404)
        return api_ok(replace_draft(version_id,p.get('nodes',[]),p.get('edges',[])))
    except ValueError as e:return api_error('DRAFT_INVALID',str(e),422)
@app.route('/api/topologies/<int:topology_id>/drafts/<int:version_id>/commit',methods=['POST'])
def draft_commit(topology_id,version_id):
    try:
        with connection() as conn:
            if not conn.execute('SELECT id FROM topology_versions WHERE id=? AND topology_id=?',(version_id,topology_id)).fetchone():return api_error('TOPOLOGY_VERSION_NOT_FOUND','Topology version does not exist',404)
        return api_ok(commit_draft(version_id))
    except ValueError as e:return api_error('COMMIT_REJECTED',str(e),422)
@app.route('/api/topology/gns3',methods=['POST'])
def fetch_live_gns3():
    if Gns3Connector is None or Project is None:return api_error('GNS3_CLIENT_MISSING','gns3fy is not installed. Install requirements.txt before using live GNS3 sync.',503)
    p=request.get_json(silent=True) or {}; url=str(p.get('server_url') or 'http://localhost:3080').strip().rstrip('/'); pid=str(p.get('project_id') or '').strip()
    if not pid:return api_error('PROJECT_ID_REQUIRED','GNS3 Project UUID is required',422)
    try:
        project=Project(project_id=pid,connector=Gns3Connector(url=url)); project.get(); nodes=[{'id':n.node_id,'node_key':n.node_id,'label':n.name,'x':n.x or 0,'y':n.y or 0,'type':infer_type(n.name),'title':f'Device: {n.name}\\nType: {n.node_type}','metadata':{'gns3_node_id':n.node_id,'node_type':n.node_type}} for n in project.nodes]; edges=[]
        for link in project.links:
            if len(link.nodes)>=2:edges.append({'id':link.link_id,'from':link.nodes[0]['node_id'],'to':link.nodes[1]['node_id'],'dashes':bool(link.suspend),'width':2})
        return api_ok({'nodes':nodes,'edges':edges,'source':'gns3','server_url':url,'project_id':pid})
    except Exception as e:return api_error('GNS3_SYNC_FAILED',f'Failed to connect to GNS3: {e}',502)
@app.route('/api/save_topology',methods=['POST'])
def save_topology():
    p=request.get_json(silent=True) or {}
    try:return api_ok({'message':'Topology committed','commit':persist_topology(p.get('name') or 'default',p.get('nodes',[]),p.get('edges',[]),'local')},201)
    except (ValueError,TypeError) as e:return api_error('INVALID_TOPOLOGY',str(e),422)
@app.route('/api/config/<node_name>',methods=['GET','POST'])
def manage_config(node_name):
    safe=secure_filename(node_name)
    if safe!=node_name:return api_error('INVALID_NODE_NAME','Invalid node name',400)
    path=CONFIG_DIR/f'{safe.lower()}.json'
    if request.method=='GET':return api_ok({'content':path.read_text(encoding='utf-8')}) if path.exists() else api_ok({'content':json.dumps({'hostname':node_name,'interfaces':[],'protocols':[],'status':'enabled'},indent=2)})
    content=(request.get_json(silent=True) or {}).get('content')
    if not isinstance(content,str):return api_error('INVALID_CONFIG','content must be a JSON string',422)
    try:parsed=json.loads(content)
    except json.JSONDecodeError as e:return api_error('INVALID_JSON',str(e),422)
    path.write_text(json.dumps(parsed,indent=2)+'\n',encoding='utf-8'); return api_ok({'message':'Configuration saved'})
@app.route('/api/import_topology',methods=['POST'])
def import_topology():
    uploaded=request.files.get('file')
    if uploaded is None or not uploaded.filename:return api_error('FILE_REQUIRED','No topology file was supplied',400)
    filename=secure_filename(uploaded.filename)
    if Path(filename).suffix.lower() not in {'.json','.gns3'}:return api_error('UNSUPPORTED_FILE','Only .json and .gns3 files are supported',415)
    path=UPLOAD_DIR/filename; uploaded.save(path)
    if TopologyImporter is None:return api_error('IMPORTER_UNAVAILABLE','Topology importer is not installed',503)
    try:
        importer=TopologyImporter(target_yaml=str(CONFIG_DIR/'devices.yaml')); importer.import_json(str(path)) if path.suffix.lower()=='.json' else importer.import_gns3(str(path)); return api_ok({'message':f'Successfully imported {filename}'})
    except (OSError,ValueError,KeyError,TypeError) as e:return api_error('IMPORT_FAILED',str(e),422)
if __name__=='__main__': ensure_schema(); print('[*] NetForge Control Plane: http://127.0.0.1:5000'); app.run(host='0.0.0.0',port=int(os.getenv('NETFORGE_PORT','5000')),debug=os.getenv('NETFORGE_DEBUG','0')=='1')
