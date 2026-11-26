from __future__ import annotations
import hashlib
import sqlite3
from datetime import datetime, timezone
import pytest
from lib.repositories import SQLiteDatabase
from lib.services.device_inventory import DeviceInventoryService
from lib.services.network_intent import NetworkIntentService
from lib.services.native_configuration_snapshots import NativeConfigurationSnapshotConflict,NativeConfigurationSnapshotError,NativeConfigurationSnapshotNotFound,NativeConfigurationSnapshotService
from lib.services.topology_studio import TopologyStudioService

@pytest.fixture
def native_configuration_env(tmp_path):
 db=SQLiteDatabase(tmp_path/"native-config.sqlite");db.initialize();now=datetime.now(timezone.utc).isoformat()
 with db.transaction(immediate=True) as c:
  c.execute("INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",("org-1","org","Organization","ACTIVE",now,now))
  c.execute("INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",("project-1","org-1","project","Project","ACTIVE",now,now))
  c.execute("INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",("lab-1","project-1","Lab","gns3",1,"ACTIVE",now,now))
 topo=TopologyStudioService(db)
 profile=topo.create_profile(project_id="project-1",name="Native config lab",scope_type="LAB",scope_id="lab-1",actor="owner")
 rev=topo.create_revision(profile["profile_id"],definition={"nodes":[{"id":"router-a","name":"Router A","node_type":"ROUTER","template_id":"","x":100,"y":100,"vendor":"Cisco","operating_system":"IOS-XE"}],"links":[]},actor="owner")
 topo.publish(profile["profile_id"],rev["revision_id"],actor="owner")
 devices=DeviceInventoryService(db)
 device=devices.create({"project_id":"project-1","lab_id":"lab-1","device_key":"router-a","name":"Router A","device_type":"ROUTER","host":"192.0.2.10","vendor":"Cisco","model":"IOS-XE","username":"operator"},actor="owner")
 intent=NetworkIntentService(db,topo)
 iprofile=intent.create_profile(project_id="project-1",topology_profile_id=profile["profile_id"],name="Router A intent",actor="owner")
 irevision=intent.create_revision(iprofile["profile_id"],topology_revision_id=rev["revision_id"],definition={"schema_version":"1.0","targets":[{"logical_node_id":"router-a","device_id":device["device_id"]}]},actor="owner")
 intent.publish(iprofile["profile_id"],irevision["revision_id"],actor="owner")
 report=intent.record_capability_report(project_id="project-1",device_id=device["device_id"],platform="Cisco IOS XE",software_version="17.12",adapter_name="iosxe-discovery",adapter_version="1.0",capabilities={"addressing.ipv4":{"status":"SUPPORTED","constraints":{}}},actor="discovery",source_type="DEVICE_DISCOVERY")
 service=NativeConfigurationSnapshotService(db,topology_studio=topo,device_inventory=devices,network_intent=intent)
 return db,service,profile,rev,device,irevision,report

def test_snapshot_binds_published_intent_device_and_observed_platform(native_configuration_env):
 db,service,profile,rev,device,irevision,report=native_configuration_env
 content=b"hostname edge-router\ninterface GigabitEthernet0/0\n description uplink\n"
 result=service.record_snapshot(profile["profile_id"],topology_revision_id=rev["revision_id"],logical_node_id="router-a",device_id=device["device_id"],configuration_kind="NATIVE_SOURCE",format_id="IOS_XE_CLI",filename="edge-router.cfg",content=content,actor="owner")
 assert result["adapter_id"]=="cisco_iosxe" and result["software_version"]=="17.12"
 assert result["capability_sha256"]==report["capability_sha256"] and result["metadata"]["intent_revision_id"]==irevision["revision_id"]
 assert result["sha256"]==hashlib.sha256(content).hexdigest() and "content_bytes" not in result
 assert len(service.list_snapshots(profile["profile_id"],topology_revision_id=rev["revision_id"]))==1
 assert service.get_snapshot(result["snapshot_id"],include_content=True)["content_bytes"]==content

@pytest.mark.parametrize("content",[
 b"username admin password plain-text-secret\n",b"enable secret 5 abcdef012345\n",b"snmp-server community public RO\n",
 b"set system root-authentication encrypted-password \"$6$hash\"\n",b"-----BEGIN OPENSSH PRIVATE KEY-----\nkey\n",b"set deviceconfig system api-key abc123\n",
])
def test_inline_credentials_are_rejected(native_configuration_env,content):
 _db,service,profile,rev,device,_intent,_report=native_configuration_env
 with pytest.raises(NativeConfigurationSnapshotError,match="credential material"):
  service.record_snapshot(profile["profile_id"],topology_revision_id=rev["revision_id"],logical_node_id="router-a",device_id=device["device_id"],configuration_kind="CANDIDATE_CONFIG",format_id="IOS_XE_CLI",filename="candidate.cfg",content=content,actor="owner")

def test_snapshot_rejects_unsupported_format_and_unbound_node(native_configuration_env):
 _db,service,profile,rev,device,_intent,_report=native_configuration_env
 with pytest.raises(NativeConfigurationSnapshotConflict,match="not supported by the observed"):
  service.record_snapshot(profile["profile_id"],topology_revision_id=rev["revision_id"],logical_node_id="router-a",device_id=device["device_id"],configuration_kind="NATIVE_SOURCE",format_id="JUNOS_SET",filename="candidate.set",content=b"set system host-name edge\n",actor="owner")
 with pytest.raises(NativeConfigurationSnapshotNotFound):
  service.record_snapshot(profile["profile_id"],topology_revision_id=rev["revision_id"],logical_node_id="missing-node",device_id=device["device_id"],configuration_kind="NATIVE_SOURCE",format_id="IOS_XE_CLI",filename="candidate.cfg",content=b"hostname edge\n",actor="owner")

def test_snapshots_are_audited_and_append_only(native_configuration_env):
 db,service,profile,rev,device,_intent,_report=native_configuration_env
 result=service.record_snapshot(profile["profile_id"],topology_revision_id=rev["revision_id"],logical_node_id="router-a",device_id=device["device_id"],configuration_kind="CANDIDATE_CONFIG",format_id="IOS_XE_CLI",filename="candidate.cfg",content=b"hostname candidate\n",actor="operator")
 with db.transaction(immediate=True) as c:
  with pytest.raises(sqlite3.IntegrityError,match="immutable"):c.execute("UPDATE native_configuration_snapshots SET filename='changed.cfg' WHERE snapshot_id=?",(result["snapshot_id"],))
  with pytest.raises(sqlite3.IntegrityError,match="cannot be deleted"):c.execute("DELETE FROM native_configuration_snapshots WHERE snapshot_id=?",(result["snapshot_id"],))
  row=c.execute("SELECT action FROM audit_events WHERE resource_id=?",(result["snapshot_id"],)).fetchone()
 assert row["action"]=="NATIVE_CONFIGURATION_SNAPSHOT_RECORDED"
