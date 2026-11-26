from __future__ import annotations

import json
from io import BytesIO
import hashlib
import pytest

from dashboard.app import create_app
from lib.repositories import SQLiteDatabase
from lib.security import AuthManager

from lib.native_topology import NativeTopologyCodecError, default_registry
from lib.native_topology.cml import CMLTopologyCodec
from lib.native_topology.eve_ng import EVENGTopologyCodec
from lib.native_topology.gns3 import GNS3TopologyCodec
from lib.native_topology.helpers import parse_json, parse_xml, parse_yaml


GNS3_SOURCE = json.dumps({
    "name": "Fixture GNS3 Lab",
    "project_id": "project-fixture-id",
    "type": "topology",
    "revision": 9,
    "version": "2.2.0",
    "scene_width": 1200,
    "scene_height": 800,
    "zoom": 1.25,
    "compute": {"name": "local", "extra_vendor_field": {"retain": True}},
    "topology": {
        "nodes": [
            {
                "node_id": "gns3-node-a", "name": "R1", "node_type": "dynamips",
                "compute_id": "local", "template_id": "c7200",
                "x": 100, "y": 120, "width": 70, "height": 45,
                "ports": [{"adapter_number": 0, "port_number": 0, "name": "FastEthernet0/0"}],
                "properties": {"custom": "keep"},
            },
            {
                "node_id": "gns3-node-b", "name": "R2", "node_type": "dynamips",
                "compute_id": "local", "template_id": "c7200",
                "x": 340, "y": 180, "width": 70, "height": 45,
            },
        ],
        "links": [
            {
                "link_id": "gns3-link-1",
                "nodes": [
                    {"node_id": "gns3-node-a", "adapter_number": 0, "port_number": 0},
                    {"node_id": "gns3-node-b", "adapter_number": 0, "port_number": 0},
                ],
                "label": "R1-R2",
            }
        ],
        "drawings": [{"drawing_id": "drawing-1", "svg": "<svg>retained</svg>"}],
    },
}, separators=(",", ":")).encode()


CML_SOURCE = b"""lab:
  title: CML Fixture
  version: 0.1.0
  description: preserve this lab metadata
nodes:
  - id: n0
    label: R1
    node_definition: iosv
    x: 100
    y: 200
    configuration: "hostname R1"
    interfaces:
      - {id: i0, label: GigabitEthernet0/0}
  - id: n1
    label: SW1
    node_definition: iosvl2
    x: 420
    y: 220
    interfaces:
      - {id: i0, label: GigabitEthernet0/0}
links:
  - id: l0
    n1: n0
    n2: n1
    i1: i0
    i2: i0
    label: R1-to-SW1
annotations:
  - type: rectangle
    x1: 20
    y1: 30
    x2: 600
    y2: 400
    color: "#eeeeee"
    border_color: "#222222"
    thickness: 2
    z_index: 1
  - type: text
    x1: 50
    y1: 55
    text_content: "Backbone"
    color: "#111111"
    text_size: 14
    z_index: 2
"""


EVE_SOURCE = b"""<?xml version="1.0" encoding="UTF-8"?>
<lab name="EVE Fixture" id="fdf1f563-10f0-4596-9ae6-57407451d2f0" version="1" grid="1">
  <topology>
    <nodes>
      <node id="1" name="R1" type="iol" template="iol" image="ios.bin" left="100" top="120">
        <interface id="0" name="e0/0" type="ethernet" network_id="10" />
      </node>
      <node id="2" name="R2" type="iol" template="iol" image="ios.bin" left="420" top="130">
        <interface id="0" name="e0/0" type="ethernet" network_id="10" />
      </node>
      <node id="3" name="R3" type="iol" template="iol" image="ios.bin" left="300" top="350">
        <interface id="0" name="e0/0" type="ethernet" network_id="10" />
      </node>
    </nodes>
    <networks>
      <network id="10" type="bridge" name="Shared LAN" left="280" top="220" icon="lan.png" />
    </networks>
  </topology>
</lab>
"""


VIRL_SOURCE = b"""<?xml version="1.0" encoding="UTF-8"?>
<topology xmlns="http://www.cisco.com/VIRL" schemaVersion="0.95">
  <node name="R1" type="SIMPLE" subtype="CSR1000v" location="100,100">
    <interface id="0" name="GigabitEthernet1" />
    <extensions><entry key="config" type="string">hostname R1</entry></extensions>
  </node>
  <node name="R2" type="SIMPLE" subtype="CSR1000v" location="400,120">
    <interface id="0" name="GigabitEthernet1" />
  </node>
  <connection src="/virl:topology/virl:node[1]/virl:interface[1]" dst="/virl:topology/virl:node[2]/virl:interface[1]" />
</topology>
"""


def _nodes_by_name(definition):
    return {item["name"]: item for item in definition["nodes"]}


def test_default_registry_detects_native_formats_and_legacy_virl():
    registry = default_registry()
    assert {item.format_id for item in registry.descriptors()} == {
        "GNS3_PROJECT", "CML_LAB", "EVE_NG_UNL", "CISCO_PACKET_TRACER_PKT",
    }
    assert registry.detect(GNS3_SOURCE, "lab.gns3").format_id == "GNS3_PROJECT"
    assert registry.detect(CML_SOURCE, "lab.yaml").format_id == "CML_LAB"
    assert registry.detect(EVE_SOURCE, "lab.unl").format_id == "EVE_NG_UNL"
    assert registry.detect(VIRL_SOURCE, "legacy.virl").format_id == "CML_LAB"


def test_gns3_decode_maps_nodes_links_and_native_coordinate_provenance():
    decoded = GNS3TopologyCodec().decode(GNS3_SOURCE, "fixture.gns3")
    assert decoded.format_version == "2.2.0"
    assert len(decoded.topology_definition["nodes"]) == 2
    assert len(decoded.topology_definition["links"]) == 1
    nodes = _nodes_by_name(decoded.topology_definition)
    assert nodes["R1"]["interfaces"][0]["name"] == "FastEthernet0/0"
    assert decoded.presentation["layout_origin"] == "NATIVE"
    assert decoded.presentation["coordinate_space"]["offset_x"] == 100
    assert decoded.presentation["nodes"][1]["x"] == 340
    assert decoded.presentation["canvas"] == {"width": 1200, "height": 800}
    assert any("drawings" in item for item in decoded.warnings)


def test_gns3_export_changes_only_supported_presentation_fields_and_retains_unknown_source():
    codec = GNS3TopologyCodec()
    decoded = codec.decode(GNS3_SOURCE, "fixture.gns3")
    decoded.presentation["nodes"][0]["x"] = 555
    decoded.presentation["nodes"][0]["label"] = "R1-renamed"
    encoded = codec.encode(
        decoded.topology_definition, decoded.presentation,
        original_source=GNS3_SOURCE, filename="fixture.gns3",
    )
    exported = parse_json(encoded.content)
    assert exported["compute"]["extra_vendor_field"] == {"retain": True}
    assert exported["topology"]["drawings"][0]["svg"] == "<svg>retained</svg>"
    node = next(item for item in exported["topology"]["nodes"] if item["node_id"] == "gns3-node-a")
    assert node["x"] == 555
    assert node["name"] == "R1-renamed"
    assert node["properties"] == {"custom": "keep"}


def test_gns3_export_refuses_added_or_removed_canonical_nodes():
    codec = GNS3TopologyCodec()
    decoded = codec.decode(GNS3_SOURCE, "fixture.gns3")
    decoded.topology_definition["nodes"].pop()
    with pytest.raises(ValueError, match="node identity"):
        codec.encode(
            decoded.topology_definition, decoded.presentation,
            original_source=GNS3_SOURCE, filename="fixture.gns3",
        )


def test_cml_yaml_decode_maps_interfaces_annotations_and_keeps_config_out_of_topology():
    decoded = CMLTopologyCodec().decode(CML_SOURCE, "fixture.yaml")
    assert decoded.format_version == "0.1.0"
    nodes = _nodes_by_name(decoded.topology_definition)
    assert nodes["R1"]["node_type"] == "ROUTER"
    assert nodes["SW1"]["node_type"] == "SWITCH"
    assert nodes["R1"]["interfaces"][0]["name"] == "GigabitEthernet0/0"
    assert len(decoded.topology_definition["links"]) == 1
    assert [item["kind"] for item in decoded.presentation["drawings"]] == ["RECTANGLE", "TEXT"]
    assert "hostname R1" not in json.dumps(decoded.topology_definition)
    assert any("configurations" in warning for warning in decoded.warnings)


def test_cml_yaml_export_roundtrips_layout_annotations_and_unknown_fields():
    codec = CMLTopologyCodec()
    decoded = codec.decode(CML_SOURCE, "fixture.yaml")
    decoded.presentation["nodes"][0]["x"] = 777
    decoded.presentation["nodes"][0]["label"] = "R1-new"
    rectangle = decoded.presentation["drawings"][0]
    rectangle["x"] = 90
    rectangle["y"] = 95
    encoded = codec.encode(
        decoded.topology_definition, decoded.presentation,
        original_source=CML_SOURCE, filename="fixture.yaml",
    )
    exported = parse_yaml(encoded.content)
    node = next(item for item in exported["nodes"] if item["id"] == "n0")
    assert node["x"] == 777
    assert node["label"] == "R1-new"
    assert node["configuration"] == "hostname R1"
    assert exported["lab"]["description"] == "preserve this lab metadata"
    assert exported["annotations"][0]["x1"] == 90


def test_legacy_virl_xml_subset_decodes_and_exports_native_node_location():
    codec = CMLTopologyCodec()
    decoded = codec.decode(VIRL_SOURCE, "legacy.virl")
    assert decoded.format_version == "VIRL-0.95"
    assert len(decoded.topology_definition["nodes"]) == 2
    assert len(decoded.topology_definition["links"]) == 1
    decoded.presentation["nodes"][0]["x"] = 255
    encoded = codec.encode(
        decoded.topology_definition, decoded.presentation,
        original_source=VIRL_SOURCE, filename="legacy.virl",
    )
    root = parse_xml(encoded.content, expected_root="topology")
    first = next(item for item in list(root) if item.attrib.get("name") == "R1")
    assert first.attrib["location"].startswith("255,")
    assert any("extensions" in child.tag for child in list(first))


def test_eve_ng_shared_network_is_modelled_as_explicit_segment_node():
    decoded = EVENGTopologyCodec().decode(EVE_SOURCE, "fixture.unl")
    assert len(decoded.topology_definition["nodes"]) == 4
    assert len(decoded.topology_definition["links"]) == 3
    segment = next(item for item in decoded.topology_definition["nodes"] if item["name"] == "Shared LAN")
    assert segment["node_type"] == "SWITCH"
    assert len(segment["interfaces"]) == 3
    assert len(decoded.presentation["nodes"]) == 4
    assert len(decoded.presentation["links"]) == 3


def test_eve_ng_export_updates_device_and_network_positions_without_losing_native_attributes():
    codec = EVENGTopologyCodec()
    decoded = codec.decode(EVE_SOURCE, "fixture.unl")
    device = next(item for item in decoded.presentation["nodes"] if item["native_id"] == "node:1")
    device["x"] = 987
    network = next(item for item in decoded.presentation["nodes"] if item["native_id"] == "network:10")
    network["y"] = 654
    encoded = codec.encode(
        decoded.topology_definition, decoded.presentation,
        original_source=EVE_SOURCE, filename="fixture.unl",
    )
    root = parse_xml(encoded.content, expected_root="lab")
    router = next(item for item in root.iter() if item.tag == "node" and item.attrib.get("id") == "1")
    assert router.attrib["left"] == "987"
    assert router.attrib["image"] == "ios.bin"
    shared = next(item for item in root.iter() if item.tag == "network")
    assert shared.attrib["top"] == "654"


def test_registry_rejects_ambiguous_and_unsupported_format():
    registry = default_registry()
    with pytest.raises(NativeTopologyCodecError, match="unsupported"):
        registry.detect(b'{"hello":"world"}', "unknown.json")
    fake = GNS3TopologyCodec()
    class Ambiguous:
        format_id = "AMBIGUOUS"
        codec_name = "ambiguous"
        codec_version = "1"
        extensions = (".gns3",)
        supported_versions = ("x",)
        scope = "test"
        def detect(self, source, filename): return True
        def decode(self, source, filename): return fake.decode(source, filename)
        def encode(self, *args, **kwargs): return fake.encode(*args, **kwargs)
    registry.register(Ambiguous())
    with pytest.raises(NativeTopologyCodecError, match="ambiguous"):
        registry.detect(GNS3_SOURCE, "fixture.gns3")


@pytest.mark.parametrize(
    ("payload", "parser", "message"),
    [
        (b'{"topology":{},"topology":{}}', parse_json, "duplicate"),
        (b"lab:\n  title: one\n  title: two\n", parse_yaml, "invalid"),
        (b"lab: &lab\n  title: one\ncopy: *lab\n", parse_yaml, "invalid"),
        (b'<!DOCTYPE lab [<!ENTITY x "boom">]><lab>&x;</lab>', parse_xml, "prohibited"),
    ],
)
def test_native_parsers_reject_ambiguous_or_unsafe_documents(payload, parser, message):
    with pytest.raises(ValueError, match=message):
        parser(payload)


def test_gns3_parser_rejects_unsupported_file_revision():
    unsupported = json.dumps({"type":"topology","revision":99,"topology":{"nodes":[],"links":[]}}).encode()
    with pytest.raises(NativeTopologyCodecError, match="unsupported"):
        GNS3TopologyCodec().decode(unsupported, "future.gns3")



def _native_database(tmp_path):
    database = SQLiteDatabase(tmp_path / "native-topology.sqlite")
    database.initialize()
    now = "2026-11-26T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-native", "native-org", "Native Org", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-native", "org-native", "native-project", "Native Project", "ACTIVE", now, now),
        )
    return database


def test_native_import_service_creates_immutable_scoped_source_and_presentation(tmp_path):
    from lib.services.native_topology_interop import NativeTopologyInteropService

    database = _native_database(tmp_path)
    service = NativeTopologyInteropService(database)
    imported = service.import_file(
        project_id="project-native", name="GNS3 imported topology",
        filename="fixture.gns3", content=GNS3_SOURCE, actor="test-operator",
    )
    profile, revision = imported["profile"], imported["revision"]
    source, presentation = imported["source"], imported["presentation"]
    assert profile["project_id"] == "project-native"
    assert revision["status"] == "DRAFT"
    assert presentation["status"] == "DRAFT"
    assert presentation["source_artifact_id"] == source["source_id"]
    assert source["format_id"] == "GNS3_PROJECT"
    assert source["sha256"] == hashlib.sha256(GNS3_SOURCE).hexdigest()
    assert "source_bytes" not in source
    assert service.list_sources(profile["profile_id"])[0]["source_id"] == source["source_id"]

    service.topology_studio.publish(profile["profile_id"], revision["revision_id"], actor="test-operator")
    service.topology_presentation.publish(
        presentation["presentation_id"], actor="test-operator",
        expected_profile_id=profile["profile_id"],
    )
    exported = service.export_revision(
        profile_id=profile["profile_id"], revision_id=revision["revision_id"],
        presentation_id=presentation["presentation_id"], source_id=source["source_id"],
    )
    reopened = GNS3TopologyCodec().decode(exported.content, exported.filename)
    assert len(reopened.topology_definition["nodes"]) == 2
    assert exported.report["originating_application_reopen"] == "NOT_VERIFIED"


def test_native_topology_import_api_lists_codecs_sources_and_downloads_export(tmp_path):
    database = _native_database(tmp_path)
    client = create_app(database.path, auth_manager=AuthManager((), required=False)).test_client()

    codecs = client.get("/api/v1/topologies/native-codecs")
    assert codecs.status_code == 200
    assert {row["format_id"] for row in codecs.get_json()["data"]["items"]} == {
        "GNS3_PROJECT", "CML_LAB", "EVE_NG_UNL", "CISCO_PACKET_TRACER_PKT",
    }

    imported = client.post(
        "/api/v1/topologies/import/native",
        headers={"Idempotency-Key": "native-topology-import-0001"},
        data={
            "project_id": "project-native",
            "name": "Native API import",
            "scope_type": "PROJECT",
            "file": (BytesIO(GNS3_SOURCE), "api-fixture.gns3"),
        },
    )
    assert imported.status_code == 201, imported.get_json()
    data = imported.get_json()["data"]
    profile_id = data["profile"]["profile_id"]
    revision_id = data["revision"]["revision_id"]
    source_id = data["source"]["source_id"]
    presentation_id = data["presentation"]["presentation_id"]

    listed = client.get(f"/api/v1/topologies/{profile_id}/native-artifacts")
    assert listed.status_code == 200
    source_row = listed.get_json()["data"]["items"][0]
    assert source_row["source_id"] == source_id
    assert "source_bytes" not in source_row

    published = client.post(
        f"/api/v1/topologies/{profile_id}/publish",
        headers={"Idempotency-Key": "native-topology-publish-0001"},
        json={"revision_id": revision_id},
    )
    assert published.status_code == 200, published.get_json()
    presentation_published = client.post(
        f"/api/v1/topologies/{profile_id}/presentation-revisions/{presentation_id}/publish",
        headers={"Idempotency-Key": "native-presentation-publish-0001"},
        json={},
    )
    assert presentation_published.status_code == 200, presentation_published.get_json()

    export = client.get(
        f"/api/v1/topologies/{profile_id}/native-artifacts/{source_id}/export"
        f"?revision_id={revision_id}&presentation_id={presentation_id}"
    )
    assert export.status_code == 200
    assert "api-fixture.gns3" in export.headers["Content-Disposition"]
    assert export.headers.get("X-NetRegress-Native-Report")
    assert export.data



def test_native_json_parser_rejects_excessive_depth_item_count_and_nonfinite_constants():
    with pytest.raises(ValueError, match="invalid"):
        parse_json(b'{"value":NaN}')
    deeply_nested = (b'{"x":' * 70) + b'0' + (b'}' * 70)
    with pytest.raises(ValueError, match="invalid"):
        parse_json(deeply_nested)
    oversized_tree = b'{"items":[' + b'0,' * 250_001 + b'0]}'
    with pytest.raises(ValueError, match="invalid"):
        parse_json(oversized_tree)


@pytest.mark.parametrize(
    ("source", "filename"),
    [
        (GNS3_SOURCE, "fixture.gns3"),
        (CML_SOURCE, "fixture.yaml"),
        (VIRL_SOURCE, "fixture.virl"),
        (EVE_SOURCE, "fixture.unl"),
    ],
)
def test_native_codec_output_satisfies_the_shared_canonical_and_presentation_models(tmp_path, source, filename):
    from lib.services.topology_presentation import TopologyPresentationService
    from lib.services.topology_studio import TopologyStudioService

    decoded = default_registry().decode(source, filename)
    definition = TopologyStudioService.normalize_definition(decoded.topology_definition)
    presentation = dict(decoded.presentation)
    presentation["source_artifact_id"] = "tsr_" + ("0" * 24)
    normalized, encoded, digest = TopologyPresentationService.canonical_payload(presentation, definition)
    assert normalized["layout_origin"] == "NATIVE"
    assert normalized["source_artifact_id"] == presentation["source_artifact_id"]
    assert len(encoded) > 0
    assert len(digest) == 64



def test_gns3_codec_rejects_version_that_disagrees_with_file_revision():
    root = json.loads(GNS3_SOURCE)
    root["revision"] = 9
    root["version"] = "2.1.99"
    payload = json.dumps(root).encode()
    with pytest.raises(NativeTopologyCodecError, match="does not match"):
        GNS3TopologyCodec().decode(payload, "mismatched.gns3")


def test_cml_codec_rejects_yaml_versions_outside_declared_0_1_family():
    payload = CML_SOURCE.replace(b"version: 0.1.0", b"version: 0.2.0")
    with pytest.raises(NativeTopologyCodecError, match="0.1.x"):
        CMLTopologyCodec().decode(payload, "future.yaml")


def test_legacy_virl_codec_rejects_unsupported_schema_version_and_node_types():
    unsupported_version = VIRL_SOURCE.replace(b'schemaVersion="0.95"', b'schemaVersion="1.0"')
    with pytest.raises(NativeTopologyCodecError, match="schema version"):
        CMLTopologyCodec().decode(unsupported_version, "future.virl")

    unsupported_node = VIRL_SOURCE.replace(b'type="SIMPLE"', b'type="COMPLEX"', 1)
    with pytest.raises(ValueError, match="SIMPLE-node subset"):
        CMLTopologyCodec().decode(unsupported_node, "unsupported-node.virl")
