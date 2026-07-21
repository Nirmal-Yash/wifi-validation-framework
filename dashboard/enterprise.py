import sys
import os
import json
import yaml
import sqlite3
import subprocess
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from engine.topology_importer import TopologyImporter

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(BASE_DIR)

app = Flask(__name__)
DB_PATH = os.path.join(BASE_DIR, 'db/results.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'artifacts/uploads')
BACKUP_FOLDER = os.path.join(BASE_DIR, 'artifacts/backups')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

CONFIG_MAP = {
    '1': 'config/test_params.yaml',
    '2': 'config/devices.yaml',
    '3': 'config/hostapd.conf',
    '4': 'config/wpa_supplicant.conf'
}

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    total_tests = conn.execute("SELECT COUNT(*) as c FROM test_logs").fetchone()['c']
    passed_tests = conn.execute("SELECT COUNT(*) as c FROM test_logs WHERE status='PASSED'").fetchone()['c']
    failed_tests = total_tests - passed_tests
    pass_rate = round((passed_tests / total_tests * 100), 1) if total_tests > 0 else 0
    
    recent_failures = conn.execute("SELECT firmware_version, test_name, error_message, timestamp FROM test_logs WHERE status = 'FAILED' ORDER BY timestamp DESC LIMIT 5").fetchall()
    trend_data = [dict(row) for row in conn.execute("SELECT firmware_version, SUM(CASE WHEN status = 'PASSED' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pass_rate FROM test_logs GROUP BY firmware_version ORDER BY firmware_version ASC LIMIT 10").fetchall()]
    conn.close()
    
    return render_template('dashboard.html', total=total_tests, passed=passed_tests, failed=failed_tests, rate=pass_rate, failures=recent_failures, trends=trend_data)

@app.route('/topology')
def topology():
    return render_template('topology.html')

@app.route('/history')
def history():
    conn = get_db_connection()
    logs = conn.execute("SELECT * FROM test_logs ORDER BY timestamp DESC").fetchall()
    conn.close()
    return render_template('history.html', logs=logs)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/api/topology_data', methods=['GET'])
def topology_data():
    """Dynamically reads devices.yaml and translates it into Vis.js nodes and edges."""
    yaml_path = os.path.join(BASE_DIR, 'config/devices.yaml')
    nodes = []
    edges = []
    
    if os.path.exists(yaml_path):
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
            
        node_dict = data.get('nodes', {})
        node_id = 1
        
        # Create dynamic nodes
        for name, details in node_dict.items():
            icon_code = '\uf233' # Default server icon
            color = '#334155'
            
            if 'ap' in name.lower():
                icon_code = '\uf1eb' # Wi-Fi icon
                color = '#16a34a'
            elif 'client' in name.lower():
                icon_code = '\uf109' # Laptop icon
                color = '#4f46e5'
            elif 'monitor' in name.lower():
                icon_code = '\uf06e' # Eye icon
                color = '#e11d48'
                
            nodes.append({
                "id": node_id,
                "label": f"{name}\n({details.get('namespace', 'unknown')})",
                "icon": {"face": '"Font Awesome 6 Free"', "code": icon_code, "weight": 900, "color": color}
            })
            # Simple hierarchical chaining for dynamic edges
            if node_id > 1:
                edges.append({"from": node_id - 1, "to": node_id, "color": '#94a3b8', "dashes": True})
            node_id += 1
            
    # Fallback if empty
    if not nodes:
        nodes.append({"id": 1, "label": "No Topology Loaded", "icon": {"face": '"Font Awesome 6 Free"', "code": '\uf071', "weight": 900, "color": '#fbbf24'}})

    return jsonify({"nodes": nodes, "edges": edges})

@app.route('/api/import_topology', methods=['POST'])
def import_topology():
    if 'file' not in request.files:
        return jsonify({"error": "No file part provided."}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file."}), 400
        
    if file and file.filename.endswith('.gns3'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Create backup of old devices.yaml
        yaml_path = os.path.join(BASE_DIR, 'config/devices.yaml')
        if os.path.exists(yaml_path):
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(BACKUP_FOLDER, f'devices_backup_{timestamp}.yaml')
            os.rename(yaml_path, backup_path)
        
        try:
            importer = TopologyImporter(target_yaml=yaml_path)
            new_config = importer.import_gns3(filepath)
            return jsonify({"status": "success", "message": f"Parsed {filename}. Old topology backed up to artifacts/backups/"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    return jsonify({"error": "Invalid format. Only .gns3 supported due to Cisco PKT encryption locks."}), 400

@app.route('/api/run_validation', methods=['POST'])
def run_validation():
    fw_version = request.json.get('fw_version', 'Runtime-AdHoc')
    cmd = f"python3 -m pytest tests/ -v --fw-version={fw_version}"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=BASE_DIR)
        return jsonify({"stdout": result.stdout, "stderr": result.stderr, "success": result.returncode == 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/config/<node_id>', methods=['GET'])
def get_config(node_id):
    if node_id in CONFIG_MAP:
        filepath = os.path.join(BASE_DIR, CONFIG_MAP[node_id])
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return jsonify({"config": f.read(), "file": CONFIG_MAP[node_id]})
    return jsonify({"error": "Dynamic node config editing requires direct YAML mapping."}), 404

if __name__ == '__main__':
    print("[*] NetRegress QA Control Plane starting at http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
