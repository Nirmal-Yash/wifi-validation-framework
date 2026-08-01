import json
import yaml
import os
import re
import math

class TopologyImporter:
    def __init__(self, target_yaml='config/devices.yaml'):
        self.target_yaml = target_yaml
        self.config_dir = os.path.dirname(target_yaml)

    def import_gns3(self, filepath):
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        nodes_config = {"target_environment": {"environment_type": "localized_netns", "log_directory": "artifacts/pcaps"}, "nodes": {}}
        
        topology = data.get('topology', {})
        gns3_nodes = topology.get('nodes', [])
        if not gns3_nodes:
            gns3_nodes = data.get('nodes', [])
            
        # Parse SVG text overlays (Configurations)
        drawings = topology.get('drawings', [])
        parsed_drawings = []
        for d in drawings:
            dx, dy = d.get('x', 0), d.get('y', 0)
            svg = d.get('svg', '')
            match = re.search(r'<text[^>]*>(.*?)</text>', svg, re.DOTALL)
            if match:
                text_content = match.group(1).replace('&#10;', '\n')
                parsed_drawings.append({'x': dx, 'y': dy, 'text': text_content})
            
        for i, node in enumerate(gns3_nodes):
            name = node.get('name', f'node_{i}')
            nx = node.get('x', 0)
            ny = node.get('y', 0)
            
            # Map configuration to the geographically closest node
            closest_config = f"# Auto-generated NetForge config shell for {name}\n"
            min_dist = float('inf')
            
            for d in parsed_drawings:
                dist = math.hypot(nx - d['x'], ny - d['y'])
                if dist < 450: # Spatial threshold to prevent grabbing distant unrelated text
                    if dist < min_dist:
                        min_dist = dist
                        closest_config = d['text']
            
            nodes_config['nodes'][name] = {
                "namespace": f"{name.lower()}_ns",
                "interface": f"wlan{i}",
                "config_path": f"config/{name.lower()}.conf",
                "x": nx,
                "y": ny
            }
            
            # Write mapped config to disk immediately
            conf_file = os.path.join(self.config_dir, f"{name.lower()}.conf")
            with open(conf_file, 'w') as cf:
                cf.write(closest_config)
            
        with open(self.target_yaml, 'w') as f:
            yaml.dump(nodes_config, f)
            
        return nodes_config

    def import_json(self, filepath):
        with open(filepath, 'r') as f:
            data = json.load(f)
        with open(self.target_yaml, 'w') as f:
            yaml.dump(data, f)
        return data
