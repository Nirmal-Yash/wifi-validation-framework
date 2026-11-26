from __future__ import annotations

import json
import pytest

from lib.native_topology.cml import CMLTopologyCodec
from lib.native_topology.gns3 import GNS3TopologyCodec
from lib.services.native_topology_conversion import (
    NativeTopologyConversionError,
    NativeTopologyConversionService,
)
from tests.test_native_topology_codecs import CML_SOURCE, GNS3_SOURCE


def _gns3_switch_template():
    value = json.loads(GNS3_SOURCE)
    nodes = value["topology"]["nodes"]
    nodes[1]["name"] = "SW1"
    nodes[1]["node_type"] = "ethernet_switch"
    nodes[1]["template_id"] = "ethernet_switch"
    nodes[1]["ports"] = [{"adapter_number": 0, "port_number": 0, "name": "Ethernet0"}]
    nodes[0]["ports"] = [{"adapter_number": 0, "port_number": 0, "name": "GigabitEthernet0/0"}]
    return json.dumps(value, separators=(",", ":")).encode()


def test_cml_to_gns3_template_conversion_transfers_layout_and_reports_losses():
    target = _gns3_switch_template()
    result = NativeTopologyConversionService().convert(
        CML_SOURCE, target,
        source_filename="source.yaml",
        target_template_filename="destination.gns3",
    )
    decoded = GNS3TopologyCodec().decode(result.content, result.filename)
    report = result.report
    assert report["source"]["format_id"] == "CML_LAB"
    assert report["output"]["format_id"] == "GNS3_PROJECT"
    assert report["counts"]["nodes_mapped"] == 2
    assert report["counts"]["links_mapped"] == 1
    assert report["codec_read_back"] == "DESTINATION_CODEC_VERIFIED"
    assert any(item["category"] == "CONFIGURATION" for item in report["losses"])
    assert any(item["category"] == "DEVICE_MODEL_AND_IMAGE" for item in report["losses"])
    source_decoded = CMLTopologyCodec().decode(CML_SOURCE, "source.yaml")
    source_positions = {item["label"]: (item["x"], item["y"]) for item in source_decoded.presentation["nodes"]}
    output_positions = {item["label"]: (item["x"], item["y"]) for item in decoded.presentation["nodes"]}
    assert output_positions["R1"] == pytest.approx(source_positions["R1"])
    assert output_positions["SW1"] == pytest.approx(source_positions["SW1"])


def test_conversion_requires_bijective_semantic_node_mapping():
    target = _gns3_switch_template()
    source = CMLTopologyCodec().decode(CML_SOURCE, "source.yaml")
    destination = GNS3TopologyCodec().decode(target, "destination.gns3")
    with pytest.raises(NativeTopologyConversionError, match="one-to-one"):
        NativeTopologyConversionService().convert(
            CML_SOURCE, target, source_filename="source.yaml",
            target_template_filename="destination.gns3",
            mapping={"nodes": {"n0": "gns3-node-a", "n1": "gns3-node-a"}},
        )


def test_conversion_refuses_node_type_or_link_endpoint_mismatch():
    value = json.loads(_gns3_switch_template())
    value["topology"]["nodes"][1]["node_type"] = "dynamips"
    bad_template = json.dumps(value, separators=(",", ":")).encode()
    with pytest.raises(NativeTopologyConversionError, match="node type mismatch"):
        NativeTopologyConversionService().convert(
            CML_SOURCE, bad_template, source_filename="source.yaml",
            target_template_filename="bad.gns3",
        )


def test_conversion_refuses_same_format_and_unsafe_filename():
    with pytest.raises(NativeTopologyConversionError, match="different"):
        NativeTopologyConversionService().convert(
            CML_SOURCE, CML_SOURCE, source_filename="source.yaml",
            target_template_filename="destination.yaml",
        )
    with pytest.raises(NativeTopologyConversionError, match="filename"):
        NativeTopologyConversionService().convert(
            CML_SOURCE, _gns3_switch_template(), source_filename="../source.yaml",
            target_template_filename="destination.gns3",
        )
