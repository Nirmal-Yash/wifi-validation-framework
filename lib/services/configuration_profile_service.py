"""Versioned, Project-scoped configuration profiles and resolver integration."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
from typing import Any, Mapping

import yaml

from lib.services.configuration import ConfigurationResolver
from lib.services.configuration_schema_registry import (
    ConfigurationSchemaError, ConfigurationSchemaRegistry,
)


class ConfigurationProfileError(ValueError):
    """Invalid profile, revision, import or assignment."""


class ConfigurationProfileNotFound(LookupError):
    """Profile, revision, schema or target is not available in this Project."""


_SENSITIVE_KEY=re.compile(r"(?:password|passwd|secret|token|private.?key|api.?key|psk)",re.I)


def _canonical(value: object) -> str:
    try:
        return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    except (TypeError,ValueError) as exc:
        raise ConfigurationProfileError("configuration must contain finite JSON-compatible values") from exc


def _reject_secrets(value: object, path: str="$") -> None:
    if isinstance(value,Mapping):
        for key,child in value.items():
            if not isinstance(key,str) or not key.strip():
                raise ConfigurationProfileError(f"{path} contains an invalid key")
            if _SENSITIVE_KEY.search(key):
                raise ConfigurationProfileError(
                    f"{path}.{key}: inline secret-like fields are not allowed; attach a managed credential instead"
                )
            _reject_secrets(child,path+"."+key)
    elif isinstance(value,list):
        for index,child in enumerate(value):
            _reject_secrets(child,f"{path}[{index}]")


class ConfigurationProfileService:
    def __init__(self,database,schema_registry:ConfigurationSchemaRegistry|None=None)->None:
        self.database=database
        self.schemas=schema_registry or ConfigurationSchemaRegistry(database)

    @staticmethod
    def _now()->str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _audit(connection,actor,action,resource_type,resource_id,details):
        connection.execute(
            """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("AUD-"+secrets.token_hex(12),actor,action,resource_type,resource_id,
             json.dumps(details,sort_keys=True,separators=(",",":")),ConfigurationProfileService._now()),
        )

    @staticmethod
    def _profile(row)->dict:
        return {key:row[key] for key in (
            "profile_id","project_id","name","description","scope_type","scope_id",
            "schema_record_id","status","created_at","updated_at","created_by","updated_by",
        )}

    @staticmethod
    def _revision(row)->dict:
        return {key:row[key] for key in (
            "revision_id","profile_id","schema_record_id","revision_number","configuration_hash",
            "provenance_json","parent_revision_id","status","created_at","created_by",
            "published_at","published_by",
        )}|{"values":json.loads(row["values_json"]),"provenance":json.loads(row["provenance_json"])}

    def get_profile(self,profile_id:str)->dict|None:
        with self.database.connection() as connection:
            row=connection.execute("SELECT * FROM configuration_profiles WHERE profile_id=?",(profile_id,)).fetchone()
        return self._profile(row) if row is not None else None

    def list_profiles(self,project_id:str)->list[dict]:
        with self.database.connection() as connection:
            rows=connection.execute(
                """SELECT * FROM configuration_profiles WHERE project_id=?
                   ORDER BY scope_type,scope_id,name COLLATE NOCASE""",(project_id,)
            ).fetchall()
        return [self._profile(row) for row in rows]

    def create_profile(
        self,*,project_id:str,name:str,description:str,scope_type:str,scope_id:str,
        schema_record_id:str,actor:str,device_exists:bool=False
    )->dict:
        project_id=str(project_id or "").strip()
        name=str(name or "").strip()
        description=str(description or "").strip()
        scope_type=str(scope_type or "").strip().upper()
        actor=str(actor or "").strip()
        if not project_id or len(project_id)>128: raise ConfigurationProfileError("project_id is required")
        if not name or len(name)>120: raise ConfigurationProfileError("profile name must contain 1 to 120 characters")
        if len(description)>500: raise ConfigurationProfileError("description must be at most 500 characters")
        if scope_type not in {"PROJECT","LAB","DEVICE"}: raise ConfigurationProfileError("scope_type must be PROJECT, LAB or DEVICE")
        if not actor or len(actor)>128: raise ConfigurationProfileError("actor is required")
        schema=None
        with self.database.connection() as connection:
            schema=connection.execute(
                "SELECT schema_record_id FROM configuration_schemas WHERE schema_record_id=? AND project_id=?",
                (schema_record_id,project_id),
            ).fetchone()
            if connection.execute("SELECT 1 FROM projects WHERE project_id=?",(project_id,)).fetchone() is None:
                raise ConfigurationProfileNotFound("Project not found")
            if scope_type=="LAB":
                target=connection.execute("SELECT project_id FROM labs WHERE lab_id=?",(str(scope_id),)).fetchone()
                if target is None or target["project_id"]!=project_id:
                    raise ConfigurationProfileNotFound("Lab not found in this Project")
        if schema is None: raise ConfigurationProfileNotFound("configuration schema not found in this Project")
        if scope_type=="PROJECT": scope_id=project_id
        else:
            scope_id=str(scope_id or "").strip()
            if not scope_id or len(scope_id)>128: raise ConfigurationProfileError("scope_id is required")
            if scope_type=="DEVICE" and not device_exists:
                raise ConfigurationProfileNotFound("Device is not present in the configured device inventory")
        profile_id="cfgp_"+secrets.token_hex(12)
        now=self._now()
        with self.database.transaction(immediate=True) as connection:
            try:
                connection.execute(
                    """INSERT INTO configuration_profiles(
                        profile_id,project_id,name,description,scope_type,scope_id,schema_record_id,
                        status,created_at,updated_at,created_by,updated_by
                    ) VALUES(?,?,?,?,?,?,?,'DRAFT',?,?,?,?)""",
                    (profile_id,project_id,name,description,scope_type,scope_id,schema_record_id,now,now,actor,actor),
                )
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise ConfigurationProfileError("a profile with this name already exists at the selected scope") from exc
                raise
            self._audit(connection,actor,"CONFIGURATION_PROFILE_CREATED","CONFIGURATION_PROFILE",profile_id,
                        {"project_id":project_id,"scope_type":scope_type,"scope_id":scope_id})
        return self.get_profile(profile_id) or {}

    def list_revisions(self,profile_id:str)->list[dict]:
        with self.database.connection() as connection:
            rows=connection.execute(
                "SELECT * FROM configuration_revisions WHERE profile_id=? ORDER BY revision_number DESC",
                (profile_id,),
            ).fetchall()
        return [self._revision(row) for row in rows]

    def get_revision(self,revision_id:str)->dict|None:
        with self.database.connection() as connection:
            row=connection.execute("SELECT * FROM configuration_revisions WHERE revision_id=?",(revision_id,)).fetchone()
        return self._revision(row) if row is not None else None

    def create_revision(
        self,profile_id:str,*,values:Mapping[str,Any],actor:str,provenance:Mapping[str,Any]|None=None,
        parent_revision_id:str|None=None
    )->dict:
        profile=self.get_profile(profile_id)
        if profile is None: raise ConfigurationProfileNotFound("configuration profile not found")
        if profile["status"]=="ARCHIVED": raise ConfigurationProfileError("archived profiles cannot receive revisions")
        if not isinstance(values,Mapping): raise ConfigurationProfileError("configuration values must be an object")
        _reject_secrets(values)
        validation=self.schemas.validate(
            profile["project_id"],
            self._schema_identity(profile["schema_record_id"])[0],
            self._schema_identity(profile["schema_record_id"])[1],
            dict(values),
        )
        if not validation["valid"]:
            raise ConfigurationProfileError("configuration does not satisfy its registered schema: "+json.dumps(validation["errors"],sort_keys=True))
        canonical_values=_canonical(validation["values"])
        normalized_provenance=dict(provenance or {"source":"dashboard","schema_record_id":profile["schema_record_id"]})
        provenance_json=_canonical(normalized_provenance)
        digest=hashlib.sha256(canonical_values.encode("utf-8")).hexdigest()
        if parent_revision_id:
            parent=self.get_revision(parent_revision_id)
            if parent is None or parent["profile_id"]!=profile_id:
                raise ConfigurationProfileNotFound("parent revision does not belong to this profile")
        revision_id="cfgr_"+secrets.token_hex(12)
        now=self._now()
        with self.database.transaction(immediate=True) as connection:
            number=int(connection.execute(
                "SELECT COALESCE(MAX(revision_number),0)+1 FROM configuration_revisions WHERE profile_id=?",
                (profile_id,),
            ).fetchone()[0])
            connection.execute(
                """INSERT INTO configuration_revisions(
                    revision_id,profile_id,schema_record_id,revision_number,values_json,
                    configuration_hash,provenance_json,parent_revision_id,status,created_at,created_by,
                    published_at,published_by
                ) VALUES(?,?,?,?,?,?,?,?,'DRAFT',?,?,NULL,NULL)""",
                (revision_id,profile_id,profile["schema_record_id"],number,canonical_values,digest,
                 provenance_json,parent_revision_id,now,actor),
            )
            self._audit(connection,actor,"CONFIGURATION_REVISION_CREATED","CONFIGURATION_REVISION",revision_id,
                        {"profile_id":profile_id,"revision_number":number,"configuration_hash":digest})
        return self.get_revision(revision_id) or {}

    def _schema_identity(self,schema_record_id:str)->tuple[str,int]:
        with self.database.connection() as connection:
            row=connection.execute(
                "SELECT schema_id,version FROM configuration_schemas WHERE schema_record_id=?",
                (schema_record_id,),
            ).fetchone()
        if row is None: raise ConfigurationProfileNotFound("configuration schema not found")
        return row["schema_id"],int(row["version"])

    def publish(self,profile_id:str,revision_id:str,*,actor:str)->dict:
        profile=self.get_profile(profile_id)
        revision=self.get_revision(revision_id)
        if profile is None or revision is None or revision["profile_id"]!=profile_id:
            raise ConfigurationProfileNotFound("profile or revision not found")
        if revision["status"]!="DRAFT": raise ConfigurationProfileError("only draft revisions can be published")
        schema_id,schema_version=self._schema_identity(revision["schema_record_id"])
        validation=self.schemas.validate(profile["project_id"],schema_id,schema_version,revision["values"])
        if not validation["valid"]: raise ConfigurationProfileError("revision is no longer valid against its registered schema")
        now=self._now()
        with self.database.transaction(immediate=True) as connection:
            cursor=connection.execute(
                """UPDATE configuration_revisions SET status='PUBLISHED',published_at=?,published_by=?
                   WHERE revision_id=? AND status='DRAFT'""",(now,actor,revision_id)
            )
            if cursor.rowcount!=1: raise ConfigurationProfileError("revision changed during publish")
            connection.execute(
                "UPDATE configuration_profiles SET status='PUBLISHED',updated_at=?,updated_by=? WHERE profile_id=?",
                (now,actor,profile_id),
            )
            self._audit(connection,actor,"CONFIGURATION_REVISION_PUBLISHED","CONFIGURATION_REVISION",revision_id,
                        {"profile_id":profile_id,"configuration_hash":revision["configuration_hash"]})
        return self.get_revision(revision_id) or {}

    def rollback(self,profile_id:str,source_revision_id:str,*,actor:str)->dict:
        source=self.get_revision(source_revision_id)
        if source is None or source["profile_id"]!=profile_id:
            raise ConfigurationProfileNotFound("source revision does not belong to this profile")
        if source["status"]!="PUBLISHED":
            raise ConfigurationProfileError("rollback source must be a published revision")
        return self.create_revision(
            profile_id,values=source["values"],actor=actor,
            provenance={"source":"rollback","source_revision_id":source_revision_id,
                        "source_configuration_hash":source["configuration_hash"]},
            parent_revision_id=source_revision_id,
        )

    def _target_valid(self,project_id:str,target_type:str,target_id:str)->bool:
        with self.database.connection() as connection:
            if target_type=="PROJECT":
                return target_id==project_id and connection.execute("SELECT 1 FROM projects WHERE project_id=?",(project_id,)).fetchone() is not None
            if target_type=="LAB":
                row=connection.execute("SELECT project_id FROM labs WHERE lab_id=?",(target_id,)).fetchone()
                return row is not None and row["project_id"]==project_id
        return bool(target_type=="DEVICE" and target_id)

    def apply(self,profile_id:str,revision_id:str,*,target_type:str,target_id:str,actor:str)->dict:
        profile=self.get_profile(profile_id)
        revision=self.get_revision(revision_id)
        if profile is None or revision is None or revision["profile_id"]!=profile_id:
            raise ConfigurationProfileNotFound("profile or revision not found")
        if revision["status"]!="PUBLISHED": raise ConfigurationProfileError("only a published revision may be assigned")
        target_type=str(target_type or "").strip().upper()
        target_id=str(target_id or "").strip()
        if target_type not in {"PROJECT","LAB","DEVICE"} or not self._target_valid(profile["project_id"],target_type,target_id):
            raise ConfigurationProfileNotFound("assignment target not found in this Project")
        if profile["scope_type"] not in {"PROJECT",target_type}:
            raise ConfigurationProfileError("profile scope is incompatible with the assignment target")
        now=self._now()
        assignment_id="cfga_"+secrets.token_hex(12)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO configuration_assignments(
                    assignment_id,project_id,target_type,target_id,profile_id,revision_id,assigned_at,assigned_by
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(project_id,target_type,target_id) DO UPDATE SET
                    assignment_id=excluded.assignment_id,profile_id=excluded.profile_id,
                    revision_id=excluded.revision_id,assigned_at=excluded.assigned_at,assigned_by=excluded.assigned_by""",
                (assignment_id,profile["project_id"],target_type,target_id,profile_id,revision_id,now,actor),
            )
            self._audit(connection,actor,"CONFIGURATION_REVISION_ASSIGNED","CONFIGURATION_ASSIGNMENT",assignment_id,
                        {"project_id":profile["project_id"],"target_type":target_type,"target_id":target_id,
                         "profile_id":profile_id,"revision_id":revision_id})
        return {"assignment_id":assignment_id,"project_id":profile["project_id"],"target_type":target_type,
                "target_id":target_id,"profile_id":profile_id,"revision_id":revision_id,"assigned_at":now,"assigned_by":actor}

    def list_assignments(self,project_id:str)->list[dict]:
        with self.database.connection() as connection:
            rows=connection.execute(
                """SELECT * FROM configuration_assignments WHERE project_id=?
                   ORDER BY target_type,target_id""",(project_id,)
            ).fetchall()
        return [{key:row[key] for key in row.keys()} for row in rows]

    def resolve(
        self,project_id:str,*,lab_id:str|None=None,device_id:str|None=None,
        environment:Mapping[str,Any]|None=None,run:Mapping[str,Any]|None=None,
        test_override:Mapping[str,Any]|None=None
    )->dict:
        targets=[("PROJECT",project_id)]
        if lab_id: targets.append(("LAB",lab_id))
        if device_id: targets.append(("DEVICE",device_id))
        assigned={}
        with self.database.connection() as connection:
            for target_type,target_id in targets:
                row=connection.execute(
                    """SELECT r.*,p.scope_type,p.scope_id,p.name AS profile_name
                       FROM configuration_assignments a
                       JOIN configuration_revisions r ON r.revision_id=a.revision_id
                       JOIN configuration_profiles p ON p.profile_id=a.profile_id
                       WHERE a.project_id=? AND a.target_type=? AND a.target_id=? AND r.status='PUBLISHED'""",
                    (project_id,target_type,target_id),
                ).fetchone()
                if row:
                    assigned[target_type]={
                        "revision_id":row["revision_id"],"profile_id":row["profile_id"],
                        "revision_number":row["revision_number"],"profile_name":row["profile_name"],
                        "values":json.loads(row["values_json"]),"configuration_hash":row["configuration_hash"],
                    }
        resolved=ConfigurationResolver().resolve(
            defaults=assigned.get("PROJECT",{}).get("values"),
            environment=environment,
            lab=assigned.get("LAB",{}).get("values"),
            device=assigned.get("DEVICE",{}).get("values"),
            run=run,
            test_override=test_override,
        )
        return {
            "project_id":project_id,"lab_id":lab_id,"device_id":device_id,
            "assignments":{key:{k:v for k,v in val.items() if k!="values"} for key,val in assigned.items()},
            "values":dict(resolved.values),"configuration_hash":resolved.configuration_hash,
            "provenance":{key:list(value) for key,value in resolved.provenance.items()},
        }

    @staticmethod
    def import_yaml(yaml_text:str)->dict:
        if not isinstance(yaml_text,str) or not yaml_text.strip():
            raise ConfigurationProfileError("yaml_text must not be empty")
        if len(yaml_text.encode("utf-8"))>1024*1024:
            raise ConfigurationProfileError("YAML import exceeds the 1 MiB limit")
        try:
            parsed=yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            raise ConfigurationProfileError("YAML could not be parsed safely") from exc
        if not isinstance(parsed,dict):
            raise ConfigurationProfileError("YAML root must be an object")
        _reject_secrets(parsed)
        _canonical(parsed)
        return {"values":parsed,"provenance":{"source":"yaml_import"}}
