from engine.topology_importer import TopologyImporter


def test_gns3_normalization_preserves_nodes_and_links():
    data = {
        "topology": {
            "nodes": [
                {"node_id": "r1", "name": "Router-1", "node_type": "router", "x": 100, "y": 200},
                {"node_id": "s1", "name": "Switch-1", "node_type": "ethernet_switch", "x": 300, "y": 200},
            ],
            "links": [{"link_id": "l1", "nodes": [{"node_id": "r1"}, {"node_id": "s1"}]}],
        }
    }
    result = TopologyImporter().import_gns3_data(data)
    assert [n["id"] for n in result["nodes"]] == ["r1", "s1"]
    assert result["nodes"][0]["type"] == "router"
    assert result["nodes"][1]["type"] == "switch"
    assert result["edges"] == [{
        "id": "l1", "from": "r1", "to": "s1",
        "source_interface": None, "target_interface": None,
        "metadata": {"source": "gns3", "suspended": False},
    }]


def test_import_does_not_write_yaml():
    importer = TopologyImporter("/tmp/netforge-test/devices.yaml")
    result = importer.import_json_data({"nodes": [{"id": "n1", "name": "Client"}], "links": []})
    assert result["nodes"][0]["id"] == "n1"
    assert result["nodes"][0]["type"] == "client"


def test_invalid_link_is_ignored():
    result = TopologyImporter().import_json_data({
        "nodes": [{"id": "a", "name": "Router"}],
        "links": [{"id": "bad", "from": "a", "to": "missing"}],
    })
    assert result["edges"] == []
