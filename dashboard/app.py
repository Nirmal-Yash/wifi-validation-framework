from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

from dashboard.db import ROOT, connection, ensure_schema

try:
    from engine.topology_importer import TopologyImporter
except ImportError:
    TopologyImporter = None

try:
    from gns3fy import Gns3Connector, Project
except ImportError:
    Gns3Connector = Project = None

TEMPLATE_DIR = ROOT / "dashboard" / "templates"
UPLOAD_DIR = ROOT / "artifacts" / "uploads"
CONFIG_DIR = ROOT / "config"
app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
app.config.update(UPLOAD_FOLDER=str(UPLOAD_DIR), MAX_CONTENT_LENGTH=16 * 1024 * 1024)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def api_error(code, message, status=400, details=None):
    return jsonify({"success": False, "error": {"code": code, "message": message, "details": details or {}}}), status


def api_ok(data=None, status=200):
    payload = {"success": True}
    if data:
        payload.update(data)
    return jsonify(payload), status


def load_yaml_topology():
    path = CONFIG_DIR / "devices.yaml"
    if not path.exists():
        return {"nodes": {}, "target_environment": {}}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("devices.yaml root must be an object")
        return data
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise RuntimeError(f"Invalid topology configuration: {exc}") from exc


def infer_type(name):
    value = str(name).lower()
    for needle, kind in (("router", "router"), ("switch", "switch"), ("ap", "access_point"), ("wifi", "access_point"), ("pc", "client"), ("client", "client"), ("monitor", "monitor")):
        if needle in value:
            return kind
    return "generic"


def ensure_topology_seed():
    with connection() as conn:
        if conn.execute("SELECT COUNT(*) c FROM topologies").fetchone()["c"]:
            return
        nodes = load_yaml_topology().get("nodes", {})
        if not nodes:
            return
        conn.execute("INSERT INTO topologies(name,description,source) VALUES(?,?,?)", ("default", "Imported from config/devices.yaml", "local"))
        topology_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO topology_versions(topology_id,version,status) VALUES(?,?,?)", (topology_id, 1, "ACTIVE"))
        version_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for key, details in nodes.items():
            details = details or {}
            conn.execute("INSERT INTO topology_nodes(topology_version_id,node_key,name,node_type,namespace,interface_name,config_path,x,y,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)", (version_id, key, key, infer_type(key), details.get("namespace"), details.get("interface"), details.get("config_path"), details.get("x", 0), details.get("y", 0), json.dumps(details)))
        conn.commit()


def topology_payload():
    ensure_topology_seed()
    with connection() as conn:
        version = conn.execute("SELECT tv.id, tv.topology_id, t.name FROM topology_versions tv JOIN topologies t ON t.id=tv.topology_id WHERE tv.status='ACTIVE' ORDER BY tv.id DESC LIMIT 1").fetchone()
        if not version:
            return {"nodes": [], "edges": [], "topology": None}
        rows = conn.execute("SELECT * FROM topology_nodes WHERE topology_version_id=? ORDER BY id", (version["id"],)).fetchall()
        links = conn.execute("SELECT * FROM topology_links WHERE topology_version_id=? ORDER BY id", (version["id"],)).fetchall()
        icons = {"access_point": "\\uf1eb", "client": "\\uf109", "router": "\\uf0e8", "switch": "\\uf6ff", "monitor": "\\uf21b"}
        nodes = [{"id": r["id"], "label": r["name"], "x": r["x"], "y": r["y"], "shape": "icon", "title": f"Device: {r['name']}\\nType: {r['node_type']}\\nNamespace: {r['namespace'] or 'N/A'}\\nInterface: {r['interface_name'] or 'N/A'}", "icon": {"face": '"Font Awesome 6 Free"', "code": icons.get(r["node_type"], "\\uf233"), "weight": 900, "size": 60}} for r in rows]
        edges = [{"id": r["id"], "from": r["source_node_id"], "to": r["target_node_id"], "width": 2} for r in links]
        return {"nodes": nodes, "edges": edges, "topology": {"id": version["topology_id"], "name": version["name"], "version_id": version["id"]}}


@app.before_request
def bootstrap():
    ensure_schema()


@app.errorhandler(Exception)
def unhandled_error(exc):
    app.logger.exception("Unhandled request error")
    if request.path.startswith("/api/"):
        return api_error("INTERNAL_ERROR", "Unexpected server error. Check the dashboard log for the exception.", 500)
    return "Internal server error", 500


@app.route("/")
def index():
    with connection() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM test_logs").fetchone()["c"]
        passed = conn.execute("SELECT COUNT(*) c FROM test_logs WHERE status='PASSED'").fetchone()["c"]
        failures = conn.execute("SELECT firmware_version,test_name,error_message,timestamp FROM test_logs WHERE status IN ('FAILED','ERROR') ORDER BY timestamp DESC LIMIT 5").fetchall()
    rate = round(passed / total * 100, 1) if total else 0
    return render_template("dashboard.html", total=total, passed=passed, failed=total-passed, rate=rate, failures=failures)


@app.route("/health")
def health():
    with connection() as conn:
        conn.execute("SELECT 1").fetchone()
    return api_ok({"service": "dashboard", "database": "ok"})


@app.route("/topology")
def topology():
    return render_template("topology.html")


@app.route("/api/topology_data")
def topology_data():
    return api_ok(topology_payload())


@app.route("/api/topology/validate", methods=["POST"])
def validate_topology():
    payload = request.get_json(silent=True) or {}
    nodes, links = payload.get("nodes", []), payload.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(links, list):
        return api_error("INVALID_TOPOLOGY", "nodes and edges must be arrays", 422)
    ids = {n.get("id") for n in nodes}
    invalid = [e for e in links if e.get("from") not in ids or e.get("to") not in ids]
    if invalid:
        return api_error("INVALID_LINK", "One or more links reference missing nodes", 422, {"count": len(invalid)})
    return api_ok({"valid": True, "node_count": len(nodes), "link_count": len(links)})


@app.route("/api/topology/gns3", methods=["POST"])
def fetch_live_gns3():
    if Gns3Connector is None or Project is None:
        return api_error("GNS3_CLIENT_MISSING", "gns3fy is not installed. Install requirements.txt before using live GNS3 sync.", 503)
    payload = request.get_json(silent=True) or {}
    server_url = str(payload.get("server_url") or "http://localhost:3080").strip().rstrip("/")
    project_id = str(payload.get("project_id") or "").strip()
    if not project_id:
        return api_error("PROJECT_ID_REQUIRED", "GNS3 Project UUID is required", 422)
    try:
        connector = Gns3Connector(url=server_url)
        project = Project(project_id=project_id, connector=connector)
        project.get()
        nodes = []
        for node in project.nodes:
            nodes.append({"id": node.node_id, "label": node.name, "x": node.x or 0, "y": node.y or 0, "shape": "box", "title": f"Device: {node.name}\\nType: {node.node_type}"})
        edges = []
        for link in project.links:
            if len(link.nodes) >= 2:
                edges.append({"id": link.link_id, "from": link.nodes[0]["node_id"], "to": link.nodes[1]["node_id"], "dashes": bool(link.suspend), "width": 2})
        return api_ok({"nodes": nodes, "edges": edges, "source": "gns3", "server_url": server_url, "project_id": project_id})
    except Exception as exc:
        return api_error("GNS3_SYNC_FAILED", f"Failed to connect to GNS3: {exc}", 502)


@app.route("/api/save_topology", methods=["POST"])
def save_topology():
    payload = request.get_json(silent=True) or {}
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return api_error("INVALID_REQUEST", "nodes array is required", 422)
    name = str(payload.get("name") or "default").strip()[:100]
    with connection() as conn:
        existing = conn.execute("SELECT id FROM topologies WHERE name=?", (name,)).fetchone()
        if existing:
            topology_id = existing["id"]
            version = conn.execute("SELECT COALESCE(MAX(version),0)+1 v FROM topology_versions WHERE topology_id=?", (topology_id,)).fetchone()["v"]
        else:
            conn.execute("INSERT INTO topologies(name,source) VALUES(?,?)", (name, "local"))
            topology_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            version = 1
        conn.execute("INSERT INTO topology_versions(topology_id,version,status) VALUES(?,?,?)", (topology_id, version, "ACTIVE"))
        version_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        id_map = {}
        for index, node in enumerate(nodes, 1):
            label = str(node.get("label") or f"node-{index}").strip()
            conn.execute("INSERT INTO topology_nodes(topology_version_id,node_key,name,node_type,x,y,metadata_json) VALUES(?,?,?,?,?,?,?)", (version_id, str(node.get("id", index)), label, infer_type(label), float(node.get("x", 0)), float(node.get("y", 0)), json.dumps(node)))
            id_map[node.get("id", index)] = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for edge in payload.get("edges", []):
            source, target = id_map.get(edge.get("from")), id_map.get(edge.get("to"))
            if source and target:
                conn.execute("INSERT INTO topology_links(topology_version_id,source_node_id,target_node_id,metadata_json) VALUES(?,?,?,?)", (version_id, source, target, json.dumps(edge)))
        conn.execute("UPDATE topology_versions SET status='ARCHIVED' WHERE topology_id=? AND id<>? AND status='ACTIVE'", (topology_id, version_id))
        conn.commit()
    return api_ok({"message": "Topology committed", "topology_id": topology_id, "version": version}, 201)


@app.route("/api/config/<node_name>", methods=["GET", "POST"])
def manage_config(node_name):
    safe_name = secure_filename(node_name)
    if safe_name != node_name:
        return api_error("INVALID_NODE_NAME", "Invalid node name", 400)
    path = CONFIG_DIR / f"{safe_name.lower()}.json"
    if request.method == "GET":
        if path.exists():
            return api_ok({"content": path.read_text(encoding="utf-8")})
        return api_ok({"content": json.dumps({"hostname": node_name, "interfaces": [], "protocols": [], "status": "enabled"}, indent=2)})
    body = request.get_json(silent=True) or {}
    content = body.get("content")
    if not isinstance(content, str):
        return api_error("INVALID_CONFIG", "content must be a JSON string", 422)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        return api_error("INVALID_JSON", str(exc), 422)
    path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
    return api_ok({"message": "Configuration saved"})


@app.route("/api/import_topology", methods=["POST"])
def import_topology():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return api_error("FILE_REQUIRED", "No topology file was supplied", 400)
    filename = secure_filename(uploaded.filename)
    if Path(filename).suffix.lower() not in {".json", ".gns3"}:
        return api_error("UNSUPPORTED_FILE", "Only .json and .gns3 files are supported", 415)
    path = UPLOAD_DIR / filename
    uploaded.save(path)
    if TopologyImporter is None:
        return api_error("IMPORTER_UNAVAILABLE", "Topology importer is not installed", 503)
    try:
        importer = TopologyImporter(target_yaml=str(CONFIG_DIR / "devices.yaml"))
        if path.suffix.lower() == ".json":
            importer.import_json(str(path))
        else:
            importer.import_gns3(str(path))
        return api_ok({"message": f"Successfully imported {filename}"})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return api_error("IMPORT_FAILED", str(exc), 422)


if __name__ == "__main__":
    ensure_schema()
    print("[*] NetForge Control Plane: http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=int(os.getenv("NETFORGE_PORT", "5000")), debug=os.getenv("NETFORGE_DEBUG", "0") == "1")
