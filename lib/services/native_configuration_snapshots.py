"""Immutable, version-bound vendor-native configuration snapshots.

Portable Network Intent remains vendor-neutral. This service stores separate,
secret-free native configuration text pinned to a published topology revision,
published node-to-Device binding and fresh observed platform/compiler capability.
It never executes configuration.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib, json, re, secrets
from lib.network_config.registry import AdapterResolutionError, NetworkConfigAdapterRegistry
from lib.services.device_inventory import DeviceInventoryService
from lib.services.network_intent import NetworkIntentService
from lib.services.topology_studio import TopologyStudioService

class NativeConfigurationSnapshotError(ValueError): pass
class NativeConfigurationSnapshotNotFound(LookupError): pass
class NativeConfigurationSnapshotConflict(NativeConfigurationSnapshotError): pass

_SECRET_LINE=re.compile(r"(?im)^\s*(?:enable\s+secret|(?:username|user)\s+\S+\s+(?:password|secret)|(?:password|passwd|secret|community|encrypted-password|authentication-key|key-string|pre-shared-key|psk|api[-_]?key|access[-_]?token|client[-_]?secret)\b).*$")
_SECRET_ASSIGNMENT=re.compile(r"(?i)\b(?:password|passwd|secret|community|encrypted-password|authentication-key|key-string|pre-shared-key|psk|api[-_]?key|access[-_]?token|client[-_]?secret)\b\s*(?:=|:|\s)\s*\S+")
_PRIVATE_KEY=re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",re.I)
_FORMATS={
 "linux_frr":{"FRR_CONF":{".conf"},"LINUX_NETWORKD":{".network"},"NFTABLES":{".nft"}},
 "cisco_iosxe":{"IOS_XE_CLI":{".txt",".cfg"}},
 "arista_eos":{"EOS_CLI":{".txt",".cfg"}},
 "juniper_junos":{"JUNOS_SET":{".set",".txt"}},
 "paloalto_panos":{"PANOS_SET":{".set",".txt"}},
}

class NativeConfigurationSnapshotService:
 MAX_CONTENT_BYTES=2*1024*1024
 CAPABILITY_MAX_AGE=timedelta(days=7)
 CAPABILITY_FUTURE_SKEW=timedelta(minutes=5)
 def __init__(self,database,*,topology_studio=None,device_inventory=None,network_intent=None,adapter_registry=None,clock=None):
  self.database=database
  self.topology=topology_studio or TopologyStudioService(database)
  self.devices=device_inventory or DeviceInventoryService(database)
  self.intent=network_intent or NetworkIntentService(database,self.topology)
  self.adapters=adapter_registry or NetworkConfigAdapterRegistry()
  self.clock=clock or (lambda:datetime.now(timezone.utc))
 @staticmethod
 def _actor(value):
  actor=str(value or "").strip()
  if not actor or len(actor)>128 or any(ord(c)<33 for c in actor):raise NativeConfigurationSnapshotError("actor must contain 1 to 128 printable characters")
  return actor
 @staticmethod
 def _content(value):
  if not isinstance(value,(bytes,bytearray,memoryview)):raise NativeConfigurationSnapshotError("configuration content must be bytes")
  content=bytes(value)
  if not content or len(content)>NativeConfigurationSnapshotService.MAX_CONTENT_BYTES or b"\x00" in content:raise NativeConfigurationSnapshotError("configuration file must contain 1 byte to 2 MiB of text")
  try:text=content.decode("utf-8-sig",errors="strict")
  except UnicodeDecodeError as exc:raise NativeConfigurationSnapshotError("configuration content must be UTF-8 text") from exc
  if any(ord(c)<32 and c not in "\n\r\t" for c in text):raise NativeConfigurationSnapshotError("configuration content contains unsupported control characters")
  if _PRIVATE_KEY.search(text) or _SECRET_LINE.search(text) or _SECRET_ASSIGNMENT.search(text):
   raise NativeConfigurationSnapshotError("configuration contains credential material; remove passwords, keys, tokens and community strings before storing")
  return content
 @staticmethod
 def _filename(value,extensions):
  if not isinstance(value,str):raise NativeConfigurationSnapshotError("filename must be a safe basename")
  name=value.strip()
  if not name or len(name)>255 or name in {".",".."} or "/" in name or "\\" in name or any(ord(c)<32 for c in name):
   raise NativeConfigurationSnapshotError("filename must be a safe basename of at most 255 characters")
  if not any(name.lower().endswith(suffix) for suffix in extensions):raise NativeConfigurationSnapshotError("filename extension does not match the selected native format")
  return name
 def _published_intent_binding(self,project_id,profile_id,revision_id,node_id,device_id):
  found=[]
  for profile in self.intent.list_profiles(project_id):
   if profile["topology_profile_id"]!=profile_id or profile["status"]!="ACTIVE":continue
   revisions=[r for r in self.intent.list_revisions(profile["profile_id"]) if r["status"]=="PUBLISHED" and r["topology_revision_id"]==revision_id]
   if not revisions:continue
   latest=max(revisions,key=lambda r:r["revision_number"])
   for target in latest["definition"].get("targets",[]):
    if target.get("logical_node_id")==node_id and target.get("device_id")==device_id:
     found.append({"intent_profile_id":profile["profile_id"],"intent_revision_id":latest["revision_id"],"intent_sha256":latest["intent_sha256"]})
  if len(found)!=1:raise NativeConfigurationSnapshotConflict("a single published Network Intent revision must bind this exact logical node to this managed Device")
  return found[0]
 def _resolve(self,profile_id,revision_id,node_id,device_id):
  profile=self.topology.get_profile(profile_id); revision=self.topology.get_revision(revision_id)
  if profile is None or revision is None or revision["profile_id"]!=profile_id:raise NativeConfigurationSnapshotNotFound("topology profile or revision not found")
  if profile["status"]!="ACTIVE" or revision["status"]!="PUBLISHED":raise NativeConfigurationSnapshotConflict("snapshots require an active profile and a published topology revision")
  if not any(n["id"]==node_id for n in revision["definition"]["nodes"]):raise NativeConfigurationSnapshotNotFound("logical node is not part of the selected topology revision")
  device=self.devices.get(device_id)
  if device is None or device["project_id"]!=profile["project_id"] or device["status"]!="ACTIVE":raise NativeConfigurationSnapshotNotFound("active managed Device not found in this Project")
  if profile["scope_type"]=="LAB" and device["lab_id"]!=profile["lab_id"]:raise NativeConfigurationSnapshotConflict("managed Device must belong to the exact Lab-scoped topology profile")
  binding=self._published_intent_binding(profile["project_id"],profile_id,revision_id,node_id,device_id)
  reports=self.intent.list_capability_reports(profile["project_id"],device_id=device_id)
  if not reports:raise NativeConfigurationSnapshotConflict("a fresh adapter-observed capability report is required")
  report=reports[0]
  if report["project_id"]!=profile["project_id"] or report["device_id"]!=device_id:raise NativeConfigurationSnapshotConflict("latest capability report is outside the target Device scope")
  observed=datetime.fromisoformat(report["observed_at"].replace("Z","+00:00"))
  if observed.tzinfo is None:raise NativeConfigurationSnapshotConflict("capability timestamp must include a timezone")
  now=self.clock()
  if not isinstance(now,datetime) or now.tzinfo is None:raise NativeConfigurationSnapshotError("snapshot clock must be timezone-aware")
  age=now.astimezone(timezone.utc)-observed.astimezone(timezone.utc)
  if age>self.CAPABILITY_MAX_AGE or age< -self.CAPABILITY_FUTURE_SKEW:raise NativeConfigurationSnapshotConflict("latest device capability report is stale or in the future")
  try:adapter=self.adapters.resolve(device,report)
  except AdapterResolutionError as exc:raise NativeConfigurationSnapshotConflict("observed platform is outside the tested native configuration adapter/version matrix") from exc
  return profile,revision,device,report,adapter,binding
 def record_snapshot(self,profile_id,*,topology_revision_id,logical_node_id,device_id,configuration_kind,format_id,filename,content,actor):
  actor=self._actor(actor)
  if configuration_kind not in {"NATIVE_SOURCE","CANDIDATE_CONFIG"}:raise NativeConfigurationSnapshotError("configuration_kind must be NATIVE_SOURCE or CANDIDATE_CONFIG")
  if not isinstance(format_id,str) or not format_id:raise NativeConfigurationSnapshotError("format_id is required")
  data=self._content(content)
  profile,revision,device,report,adapter,binding=self._resolve(profile_id,topology_revision_id,logical_node_id,device_id)
  formats=_FORMATS.get(adapter.descriptor.adapter_id,{})
  if format_id not in formats:raise NativeConfigurationSnapshotConflict("format is not supported by the observed "+adapter.descriptor.adapter_id+" adapter")
  clean_name=self._filename(filename,formats[format_id])
  snapshot_id="ncs_"+secrets.token_hex(12); digest=hashlib.sha256(data).hexdigest()
  captured=self.clock()
  if not isinstance(captured,datetime) or captured.tzinfo is None:raise NativeConfigurationSnapshotError("snapshot clock must be timezone-aware")
  now=captured.astimezone(timezone.utc).isoformat()
  metadata={"intent_profile_id":binding["intent_profile_id"],"intent_revision_id":binding["intent_revision_id"],"intent_sha256":binding["intent_sha256"],"capability_source_type":report["source_type"],"capability_observed_at":report["observed_at"]}
  metadata_json=json.dumps(metadata,sort_keys=True,separators=(",",":"),allow_nan=False)
  with self.database.transaction(immediate=True) as connection:
   connection.execute("""INSERT INTO native_configuration_snapshots(
    snapshot_id,project_id,profile_id,topology_revision_id,topology_content_sha256,
    logical_node_id,device_id,capability_report_id,capability_sha256,adapter_id,
    adapter_version,platform,software_version,configuration_kind,format_id,filename,
    content_bytes,sha256,size_bytes,metadata_json,created_at,created_by
   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
   (snapshot_id,profile["project_id"],profile_id,topology_revision_id,revision["content_sha256"],logical_node_id,device_id,
    report["report_id"],report["capability_sha256"],adapter.descriptor.adapter_id,adapter.descriptor.adapter_version,
    report["platform"],report["software_version"],configuration_kind,format_id,clean_name,data,digest,len(data),metadata_json,now,actor))
   connection.execute("""INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
    VALUES(?,?,?,?,?,?,?)""",
    ("AUD-"+secrets.token_hex(12),actor,"NATIVE_CONFIGURATION_SNAPSHOT_RECORDED","NATIVE_CONFIGURATION_SNAPSHOT",snapshot_id,
     json.dumps({"project_id":profile["project_id"],"profile_id":profile_id,"topology_revision_id":topology_revision_id,
      "logical_node_id":logical_node_id,"device_id":device_id,"adapter_id":adapter.descriptor.adapter_id,
      "format_id":format_id,"configuration_kind":configuration_kind,"sha256":digest,"size_bytes":len(data),
      "capability_sha256":report["capability_sha256"]},sort_keys=True,separators=(",",":")),now))
  return self.get_snapshot(snapshot_id) or {}
 @staticmethod
 def _serialize(row):
  if row is None:return None
  keys=("snapshot_id","project_id","profile_id","topology_revision_id","topology_content_sha256","logical_node_id","device_id",
   "capability_report_id","capability_sha256","adapter_id","adapter_version","platform","software_version","configuration_kind",
   "format_id","filename","sha256","size_bytes","created_at","created_by")
  return {key:row[key] for key in keys}|{"metadata":json.loads(row["metadata_json"])}
 def list_snapshots(self,profile_id,*,topology_revision_id=None):
  query="SELECT * FROM native_configuration_snapshots WHERE profile_id=?"; params=[profile_id]
  if topology_revision_id:query+=" AND topology_revision_id=?";params.append(topology_revision_id)
  query+=" ORDER BY created_at DESC,snapshot_id"
  with self.database.connection() as connection:rows=connection.execute(query,params).fetchall()
  return [self._serialize(row) for row in rows]
 def get_snapshot(self,snapshot_id,*,include_content=False):
  with self.database.connection() as connection:row=connection.execute("SELECT * FROM native_configuration_snapshots WHERE snapshot_id=?",(snapshot_id,)).fetchone()
  item=self._serialize(row)
  if item is not None and include_content:
   content=bytes(row["content_bytes"])
   if len(content)!=item["size_bytes"] or hashlib.sha256(content).hexdigest()!=item["sha256"]:raise NativeConfigurationSnapshotError("stored configuration failed size/SHA-256 integrity verification")
   item["content_bytes"]=content
  return item
