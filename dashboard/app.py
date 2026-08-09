# dashboard/app.py
import sys, os, json, yaml, sqlite3, subprocess, re
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

try:
    from gns3fy import Gns3Connector, Project
    GNS3FY_INSTALLED = True
except ImportError:
    GNS3FY_INSTALLED = False

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

try:
    from engine.topology_importer import TopologyImporter
except ImportError:
    TopologyImporter = None

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

            # FIX: Used native \n formatting for Vis.js to fix the literal HTML bug shown in the screenshot
            ip_disp = "Unassigned / DHCP"
            config_content = ""
            conf_path = os.path.join(BASE_DIR, 'config', f"{name_lower}.json")
            if os.path.exists(conf_path):
                try:
                    with open(conf_path, 'r') as cf:
                        parsed_json = json.load(cf)
                        interfaces = parsed_json.get("interfaces", [])
                        if interfaces and "ip" in interfaces[0]:
                            ip_disp = interfaces[0]["ip"]
                except Exception:
                    pass

            ns_disp = details.get('namespace', 'N/A')
            iface_disp = details.get('interface', 'N/A')
            
            tooltip = f"Device: {name}\nIP Address: {ip_disp}\nNamespace: {ns_disp}\nInterface: {iface_disp}"

            node_obj = {
                "id": node_id, "label": name, "title": tooltip, "shape": "icon",
                "icon": {"face": '"Font Awesome 6 Free"', "code": icon_code, "weight": 900, "color": color, "size": 60}
            }
            if 'x' in details and 'y' in details:
                node_obj['x'], node_obj['y'] = details['x'], details['y']

            nodes.append(node_obj)
            
            if prev_id: 
                edges.append({
                    "from": prev_id, "to": node_id, 
                    "color": {'color': '#64748b', 'highlight': '#ff8c00', 'hover': '#ff8c00'}, 
                    "width": 2, "dashes": False
                })
            prev_id = node_id
            node_id += 1
            
    return jsonify({"nodes": nodes or [{"id": 1, "label": "Canvas Empty", "shape": "box", "color": "#353535"}], "edges": edges})

@app.route('/api/topology/gns3', methods=['POST'])
def fetch_live_gns3():
    if not GNS3FY_INSTALLED:
        return jsonify({"error": "gns3fy library is missing. Run 'pip install gns3fy requests'"}), 500
    
    req = request.json
    server_url = req.get('server_url', 'http://localhost:3080')
    project_id = req.get('project_id')
    
    if not project_id:
        return jsonify({"error": "GNS3 Project UUID is required."}), 400

    try:
        # Dynamic connection to user-provided URL prevents Connection Refused errors
        connector = Gns3Connector(url=server_url)
        project = Project(project_id=project_id, connector=connector)
        project.get()

        conn = get_db_connection()
        recent_failures = conn.execute("SELECT test_name FROM test_logs WHERE status='FAILED' ORDER BY timestamp DESC LIMIT 5").fetchall()
        conn.close()
        
        has_auth_fail = any("auth" in f['test_name'].lower() for f in recent_failures)
        has_dhcp_fail = any("dhcp" in f['test_name'].lower() for f in recent_failures)
        error_color = "#ffb4ab"

        vis_nodes, vis_edges = [], []

        for node in project.nodes:
            name_lower = node.name.lower()
            if 'cloud' in node.node_type.lower(): icon_code, color = '\uf0c2', '#3b82f6'
            elif 'ap' in name_lower or 'wifi' in name_lower: icon_code, color = '\uf1eb', '#10b981'
            elif 'client' in name_lower or 'pc' in name_lower: icon_code, color = '\uf109', '#3b82f6'
            elif 'router' in name_lower: icon_code, color = '\uf0e8', '#8b5cf6'
            elif 'switch' in name_lower: icon_code, color = '\uf6ff', '#f59e0b'
            else: icon_code, color = '\uf233', '#94a3b8'

            if has_auth_fail and ('ap' in name_lower or 'client' in name_lower): color = error_color
            if has_dhcp_fail and ('router' in name_lower or 'client' in name_lower): color = error_color

            status_text = "CRITICAL FAILURE" if color == error_color else "ACTIVE"
            tooltip = f"Device: {node.name}\nType: {node.node_type}\nStatus: {status_text}"

            vis_nodes.append({
                "id": node.node_id, "label": node.name, "x": node.x, "y": node.y,
                "title": tooltip, "shape": "icon",
                "icon": {"face": '"Font Awesome 6 Free"', "code": icon_code, "weight": 900, "color": color, "size": 60}
            })

        for link in project.links:
            if len(link.nodes) >= 2:
                vis_edges.append({
                    "id": link.link_id, "from": link.nodes[0]['node_id'], "to": link.nodes[1]['node_id'],
                    "color": {"color": '#353535', "highlight": '#ff8c00'},
                    "width": 2, "dashes": link.suspend
                })

        return jsonify({"nodes": vis_nodes, "edges": vis_edges})

    except Exception as e:
        return jsonify({"error": f"Failed to connect to GNS3: {str(e)}"}), 500

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
            "config_path": f"config/{name.lower()}.json",
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
    if TopologyImporter:
        importer = TopologyImporter(target_yaml=os.path.join(BASE_DIR, 'config/devices.yaml'))
        importer.import_json(filepath) if file.filename.endswith('.json') else importer.import_gns3(filepath)
        return jsonify({"status": "success", "message": f"Successfully parsed {file.filename}."})
    return jsonify({"error": "TopologyImporter missing"}), 500

@app.route('/api/config/<node_name>', methods=['GET', 'POST'])
def manage_config(node_name):
    # FIX: Full JSON Validation and formatting
    config_file = os.path.join(BASE_DIR, 'config', f"{node_name.lower()}.json")
    
    if request.method == 'POST':
        content = request.json.get('content', '{}')
        try:
            parsed = json.loads(content)
            with open(config_file, 'w') as f:
                json.dump(parsed, f, indent=4)
            return jsonify({"status": "success", "message": "Configuration saved."})
        except json.JSONDecodeError as e:
            return jsonify({"status": "error", "message": f"Invalid JSON format: {str(e)}"}), 400
    else:
        content = ""
        if os.path.exists(config_file):
            with open(config_file, 'r') as f: 
                content = f.read()
        else:
            default_json = {
                "hostname": node_name,
                "interfaces": [
                    {"name": "wlan0", "ip": "192.168.50.1", "mask": "255.255.255.0"}
                ],
                "protocols": ["tcp", "udp"],
                "status": "enabled"
            }
            content = json.dumps(default_json, indent=4)
        return jsonify({"content": content})

if __name__ == '__main__':
    print("[*] NetForge Control Plane running at http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
