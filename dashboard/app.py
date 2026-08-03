import sys, os, json, yaml, sqlite3, subprocess, html, re
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)
from engine.topology_importer import TopologyImporter

TEMPLATE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates'))
app = Flask(__name__, template_folder=TEMPLATE_DIR)
DB_PATH = os.path.join(BASE_DIR, 'db/results.db')
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'artifacts/uploads')

os.makedirs(os.path.join(BASE_DIR, 'config'), exist_ok=True)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    if not os.path.exists(DB_PATH): return render_template('dashboard.html', total=0, passed=0, failed=0, rate=0, failures=[])
    conn = get_db_connection()
    total = conn.execute("SELECT COUNT(*) as c FROM test_logs").fetchone()['c']
    passed = conn.execute("SELECT COUNT(*) as c FROM test_logs WHERE status='PASSED'").fetchone()['c']
    failed = total - passed
    rate = round((passed / total * 100), 1) if total > 0 else 0
    failures = conn.execute("SELECT firmware_version, test_name, error_message, timestamp FROM test_logs WHERE status = 'FAILED' ORDER BY timestamp DESC LIMIT 5").fetchall()
    conn.close()
    return render_template('dashboard.html', total=total, passed=passed, failed=failed, rate=rate, failures=failures)

@app.route('/topology')
def topology(): return render_template('topology.html')

@app.route('/history')
def history():
    if not os.path.exists(DB_PATH):
        return render_template('history.html', logs=[], fw_list=[], fw_a=None, fw_b=None, comparisons=[])
    conn = get_db_connection()
    logs = conn.execute("SELECT * FROM test_logs ORDER BY timestamp DESC").fetchall()
    fw_list = conn.execute("SELECT DISTINCT firmware_version FROM test_logs ORDER BY firmware_version DESC").fetchall()
    fw_a, fw_b, comparisons = request.args.get('fw_a'), request.args.get('fw_b'), []
    if fw_a and fw_b:
        compare_query = """
            SELECT a.test_name, a.status as status_a, b.status as status_b
            FROM (SELECT test_name, status FROM test_logs WHERE firmware_version = ? GROUP BY test_name) a
            JOIN (SELECT test_name, status FROM test_logs WHERE firmware_version = ? GROUP BY test_name) b 
            ON a.test_name = b.test_name
        """
        comparisons = conn.execute(compare_query, (fw_a, fw_b)).fetchall()
    conn.close()
    return render_template('history.html', logs=logs, fw_list=fw_list, fw_a=fw_a, fw_b=fw_b, comparisons=comparisons)

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/api/topology_data', methods=['GET'])
def topology_data():
    yaml_path = os.path.join(BASE_DIR, 'config/devices.yaml')
    nodes, edges = [], []
    if os.path.exists(yaml_path):
        with open(yaml_path, 'r') as f: data = yaml.safe_load(f)
        node_id, prev_id = 1, None
        for name, details in data.get('nodes', {}).items():
            name_lower = name.lower()
            if 'ap' in name_lower or 'wifi' in name_lower: icon_code, color = '\uf1eb', '#10b981'
            elif 'client' in name_lower or 'pc' in name_lower: icon_code, color = '\uf109', '#3b82f6'
            elif 'router' in name_lower or 'gateway' in name_lower: icon_code, color = '\uf0e8', '#8b5cf6'
            elif 'switch' in name_lower or 'bridge' in name_lower: icon_code, color = '\uf6ff', '#f59e0b'
            elif 'monitor' in name_lower or 'sniffer' in name_lower: icon_code, color = '\uf21b', '#ec4899'
            else: icon_code, color = '\uf233', '#94a3b8'

            config_content = ""
            conf_path = os.path.join(BASE_DIR, 'config', f"{name_lower}.conf")
            if os.path.exists(conf_path):
                with open(conf_path, 'r') as cf:
                    config_content = cf.read()
            
            ip_match = re.search(r'ip address\s+([\d\.]+)', config_content, re.IGNORECASE)
            ip_display = ip_match.group(1) if ip_match else "Unassigned / DHCP"
            
            tooltip = f"<b>Device:</b> {name}<br><b>IP Address:</b> {ip_display}<br><b>Namespace:</b> {details.get('namespace', 'N/A')}<br><b>Interface:</b> {details.get('interface', 'N/A')}"

            node_obj = {
                "id": node_id,
                "label": name,
                "title": tooltip,
                "shape": "icon",
                "icon": {"face": '"Font Awesome 6 Free"', "code": icon_code, "weight": 900, "color": color, "size": 60}
            }
            
            if 'x' in details and 'y' in details:
                node_obj['x'], node_obj['y'] = details['x'], details['y']

            nodes.append(node_obj)
            
            if prev_id: 
                edges.append({
                    "from": prev_id, 
                    "to": node_id, 
                    "color": {'color': '#94a3b8', 'highlight': '#ff8c00', 'hover': '#ff8c00'}, 
                    "width": 2, 
                    "dashes": False
                })
            prev_id = node_id
            node_id += 1
            
    return jsonify({"nodes": nodes or [{"id": 1, "label": "Canvas Empty", "shape": "box", "color": "#1f1f1f"}], "edges": edges})

@app.route('/api/save_topology', methods=['POST'])
def save_topology():
    req_data = request.json
    nodes = req_data.get('nodes', [])
    devices_config = {"target_environment": {"environment_type": "localized_netns", "log_directory": "artifacts/pcaps"}, "nodes": {}}
    for n in nodes:
        name = n.get('label').strip()
        devices_config['nodes'][name] = {
            "namespace": f"{name.lower()}_ns",
            "interface": f"wlan{n.get('id', 0)}",
            "config_path": f"config/{name.lower()}.conf",
            "x": n.get('x', 0),
            "y": n.get('y', 0)
        }
    with open(os.path.join(BASE_DIR, 'config/devices.yaml'), 'w') as f:
        yaml.dump(devices_config, f)
    return jsonify({"status": "success", "message": "Topology & Coordinates committed."})

@app.route('/api/import_topology', methods=['POST'])
def import_topology():
    file = request.files.get('file')
    if not file or file.filename == '': return jsonify({"error": "No file provided."}), 400
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
    file.save(filepath)
    importer = TopologyImporter(target_yaml=os.path.join(BASE_DIR, 'config/devices.yaml'))
    importer.import_json(filepath) if file.filename.endswith('.json') else importer.import_gns3(filepath)
    return jsonify({"status": "success", "message": f"Successfully parsed {file.filename}."})

@app.route('/api/config/<node_name>', methods=['GET', 'POST'])
def manage_config(node_name):
    config_file = os.path.join(BASE_DIR, 'config', f"{node_name.lower()}.conf")
    if request.method == 'POST':
        content = request.json.get('content', '')
        with open(config_file, 'w') as f:
            f.write(content)
        return jsonify({"status": "success", "message": "Configuration saved."})
    else:
        content = ""
        if os.path.exists(config_file):
            with open(config_file, 'r') as f: content = f.read()
        return jsonify({"content": content})

if __name__ == '__main__':
    print("[*] NetForge Control Plane running at http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
