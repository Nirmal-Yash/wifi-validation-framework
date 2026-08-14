import json
import os


class TopologyImporter:
    """Normalize topology input; filesystem import remains separate from DB commit."""

    TYPE_MAP = {
        "router": "router", "switch": "switch", "ethernet_switch": "switch",
        "access point": "access_point", "access_point": "access_point", "wifi": "access_point",
        "wireless": "access_point", "vpcs": "client", "pc": "client", "client": "client",
        "cloud": "generic", "docker": "generic", "qemu": "generic",
    }

    def __init__(self, target_yaml="config/devices.yaml"):
        self.target_yaml = target_yaml
        self.config_dir = os.path.dirname(target_yaml) or "."

    def _node_type(self, node):
        raw = str(node.get("node_type") or node.get("type") or "").lower().strip()
        name = str(node.get("name") or node.get("label") or "").lower()
        for key, value in self.TYPE_MAP.items():
            if key in raw or key in name:
                return value
        return "generic"

    def _normalize(self, data, source="import"):
        topology = data.get("topology", data) if isinstance(data, dict) else {}
        raw_nodes = topology.get("nodes", []) or []
        raw_links = topology.get("links", []) or topology.get("connections", []) or []
        nodes, ids = [], set()
        for index, node in enumerate(raw_nodes):
            node_id = str(node.get("node_id") or node.get("id") or node.get("node_key") or f"node_{index + 1}")
            if node_id in ids:
                node_id = f"{node_id}_{index + 1}"
            ids.add(node_id)
            name = str(node.get("name") or node.get("label") or node_id).strip()
            nodes.append({"id":node_id,"node_key":node_id,"label":name,"type":self._node_type(node),"x":float(node.get("x") or 0),"y":float(node.get("y") or 0),"metadata":{"source":source,"gns3_node_id":node.get("node_id") or node.get("id"),"node_type":node.get("node_type") or node.get("type"),"compute_id":node.get("compute_id")}})
        edges = []
        for index, link in enumerate(raw_links):
            endpoints = link.get("nodes") or link.get("endpoints") or []
            if len(endpoints) >= 2:
                source_id = endpoints[0].get("node_id") if isinstance(endpoints[0], dict) else endpoints[0]
                target_id = endpoints[1].get("node_id") if isinstance(endpoints[1], dict) else endpoints[1]
            else:
                source_id, target_id = link.get("from") or link.get("source"), link.get("to") or link.get("target")
            source_id, target_id = str(source_id), str(target_id)
            if source_id not in ids or target_id not in ids or source_id == target_id:
                continue
            edges.append({"id":str(link.get("link_id") or link.get("id") or f"link_{index+1}"),"from":source_id,"to":target_id,"source_interface":link.get("source_interface"),"target_interface":link.get("target_interface"),"metadata":{"source":source,"suspended":bool(link.get("suspend",False))}})
        return {"source":source,"nodes":nodes,"edges":edges}

    def import_gns3_data(self, data):
        return self._normalize(data, "gns3")

    def import_json_data(self, data):
        return self._normalize(data, "import")

    def import_gns3(self, filepath):
        with open(filepath, "r", encoding="utf-8") as handle:
            normalized = self.import_gns3_data(json.load(handle))
        self.write_legacy_yaml(normalized)
        return normalized

    def import_json(self, filepath):
        with open(filepath, "r", encoding="utf-8") as handle:
            normalized = self.import_json_data(json.load(handle))
        self.write_legacy_yaml(normalized)
        return normalized

    def write_legacy_yaml(self, normalized):
        import yaml
        os.makedirs(self.config_dir, exist_ok=True)
        nodes = {n["node_key"]:{"namespace":f"{n['label'].lower().replace(' ','_')}_ns","interface":"wlan0","x":n["x"],"y":n["y"]} for n in normalized["nodes"]}
        payload = {"target_environment":{"environment_type":"localized_netns"},"nodes":nodes}
        with open(self.target_yaml,"w",encoding="utf-8") as handle:
            yaml.safe_dump(payload,handle,sort_keys=False)
        return payload
