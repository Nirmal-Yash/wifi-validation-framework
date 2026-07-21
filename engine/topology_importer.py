import json
import yaml
import zipfile
import xml.etree.ElementTree as ET
import os

class TopologyImporter:
    def __init__(self, target_yaml="config/devices.yaml"):
        self.target_yaml = target_yaml
        self.base_config = {
            "target_environment": {
                "environment_type": "dynamic_import",
                "log_directory": "artifacts/pcaps"
            },
            "nodes": {}
        }

    def import_gns3(self, filepath):
        """Parses a standard GNS3 JSON project file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
            
        nodes = data.get('topology', {}).get('nodes', [])
        for node in nodes:
            node_name = node.get('name', 'unknown').lower().replace(' ', '_')
            node_type = node.get('node_type', 'generic')
            
            self.base_config["nodes"][node_name] = {
                "namespace": f"{node_name}_ns",
                "type": node_type,
                "interface": "eth0" # Default, to be mapped by user
            }
        return self._save_yaml()

    def import_pkt(self, filepath):
        """Parses a Cisco Packet Tracer .pkt file (ZIP containing network.xml)."""
        try:
            with zipfile.ZipFile(filepath, 'r') as zip_ref:
                xml_data = zip_ref.read('network.xml')
                root = ET.fromstring(xml_data)
                
                # Packet Tracer XML namespace handling can be complex; using generic search
                for device in root.iter('DEVICE'):
                    node_name = device.get('name', 'unknown').lower().replace(' ', '_')
                    node_type = device.get('model', 'generic')
                    
                    self.base_config["nodes"][node_name] = {
                        "namespace": f"{node_name}_ns",
                        "type": node_type,
                        "interface": "eth0"
                    }
            return self._save_yaml()
        except zipfile.BadZipFile:
            raise ValueError("Invalid or encrypted .pkt file. Please use unencrypted PT files.")

    def _save_yaml(self):
        os.makedirs(os.path.dirname(self.target_yaml), exist_ok=True)
        with open(self.target_yaml, 'w') as f:
            yaml.dump(self.base_config, f, default_flow_style=False)
        return self.base_config

if __name__ == "__main__":
    # Local debugging
    import sys
    if len(sys.argv) > 1:
        importer = TopologyImporter()
        if sys.argv[1].endswith('.gns3'):
            print(importer.import_gns3(sys.argv[1]))
        elif sys.argv[1].endswith('.pkt'):
            print(importer.import_pkt(sys.argv[1]))
