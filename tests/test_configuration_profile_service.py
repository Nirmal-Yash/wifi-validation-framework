from __future__ import annotations

import json
import sqlite3

import pytest

from lib.repositories import SQLiteDatabase
from lib.services.configuration_profile_service import (
    ConfigurationProfileError, ConfigurationProfileNotFound, ConfigurationProfileService,
)
from lib.services.configuration_schema_registry import ConfigurationSchemaRegistry


@pytest.fixture
def profiles(tmp_path):
    database=SQLiteDatabase(tmp_path/"profiles.sqlite")
    database.initialize()
    now="2026-11-13T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-1","org","Organization","ACTIVE",now,now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-1","org-1","project","Project","ACTIVE",now,now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-1","project-1","Wireless Lab","gns3",1,"ACTIVE",now,now),
        )
    schemas=ConfigurationSchemaRegistry(database)
    schema=schemas.register(
        project_id="project-1",schema_id="wifi.network",version=1,name="WiFi Network",
        actor="owner",definition={
            "type":"object","required":["ssid","channel"],"additionalProperties":False,
            "properties":{
                "ssid":{"type":"string","minLength":1,"maxLength":32},
                "channel":{"type":"integer","minimum":1,"maximum":165},
                "country":{"type":"string"},
            },
        },
    )
    service=ConfigurationProfileService(database,schemas)
    return database,service,schema


def test_revision_hash_publish_and_immutability(profiles):
    database,service,schema=profiles
    profile=service.create_profile(
        project_id="project-1",name="Base WiFi",description="Project defaults",
        scope_type="PROJECT",scope_id="ignored",schema_record_id=schema["schema_record_id"],actor="owner",
    )
    revision=service.create_revision(
        profile["profile_id"],values={"ssid":"LabNet","channel":36},
        provenance={"source":"dashboard","ticket":"NET-1"},actor="owner",
    )
    assert len(revision["configuration_hash"])==64
    assert revision["status"]=="DRAFT"
    published=service.publish(profile["profile_id"],revision["revision_id"],actor="owner")
    assert published["status"]=="PUBLISHED"
    assert service.get_profile(profile["profile_id"])["status"]=="PUBLISHED"
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError,match="content is immutable"):
            connection.execute(
                "UPDATE configuration_revisions SET values_json='{}' WHERE revision_id=?",
                (revision["revision_id"],),
            )


def test_rollback_creates_new_draft_revision_without_mutating_history(profiles):
    _database,service,schema=profiles
    profile=service.create_profile(
        project_id="project-1",name="Lab WiFi",description="",
        scope_type="LAB",scope_id="lab-1",schema_record_id=schema["schema_record_id"],actor="owner",
    )
    first=service.create_revision(profile["profile_id"],values={"ssid":"Before","channel":1},actor="owner")
    service.publish(profile["profile_id"],first["revision_id"],actor="owner")
    second=service.create_revision(profile["profile_id"],values={"ssid":"After","channel":6},actor="owner")
    service.publish(profile["profile_id"],second["revision_id"],actor="owner")
    rollback=service.rollback(profile["profile_id"],first["revision_id"],actor="owner")
    assert rollback["revision_number"]==3
    assert rollback["status"]=="DRAFT"
    assert rollback["values"]=={"ssid":"Before","channel":1}
    assert rollback["parent_revision_id"]==first["revision_id"]


def test_apply_and_resolve_use_existing_resolver_precedence(profiles):
    _database,service,schema=profiles
    project_profile=service.create_profile(
        project_id="project-1",name="Defaults",description="",scope_type="PROJECT",
        scope_id="project-1",schema_record_id=schema["schema_record_id"],actor="owner",
    )
    project_revision=service.create_revision(project_profile["profile_id"],values={"ssid":"Base","channel":1},actor="owner")
    service.publish(project_profile["profile_id"],project_revision["revision_id"],actor="owner")
    service.apply(project_profile["profile_id"],project_revision["revision_id"],
                  target_type="PROJECT",target_id="project-1",actor="owner")
    lab_profile=service.create_profile(
        project_id="project-1",name="Lab Override",description="",scope_type="LAB",
        scope_id="lab-1",schema_record_id=schema["schema_record_id"],actor="owner",
    )
    lab_revision=service.create_revision(lab_profile["profile_id"],values={"ssid":"LabNet","channel":36},actor="owner")
    service.publish(lab_profile["profile_id"],lab_revision["revision_id"],actor="owner")
    service.apply(lab_profile["profile_id"],lab_revision["revision_id"],
                  target_type="LAB",target_id="lab-1",actor="owner")
    resolved=service.resolve(
        "project-1",lab_id="lab-1",environment={"country":"IN"},
        run={"channel":44},test_override={"ssid":"TestNet"},
    )
    assert resolved["values"]=={"ssid":"TestNet","channel":44,"country":"IN"}
    assert resolved["configuration_hash"]
    assert resolved["provenance"]["ssid"]==["defaults","lab","test_override"]
    assert resolved["provenance"]["channel"]==["defaults","lab","run"]
    assert len(resolved["assignments"])==2


def test_yaml_import_is_safe_and_rejects_inline_secret_fields():
    imported=ConfigurationProfileService.import_yaml("ssid: LabNet\nchannel: 44\n")
    assert imported["values"]=={"ssid":"LabNet","channel":44}
    with pytest.raises(ConfigurationProfileError,match="inline secret-like fields"):
        ConfigurationProfileService.import_yaml("ssid: LabNet\npassword: plaintext-secret\n")
    with pytest.raises(ConfigurationProfileError,match="safely"):
        ConfigurationProfileService.import_yaml("!!python/object/apply:os.system ['id']")


def test_scope_and_project_boundaries_are_enforced(profiles):
    _database,service,schema=profiles
    with pytest.raises(ConfigurationProfileNotFound):
        service.create_profile(
            project_id="project-1",name="Foreign lab",description="",scope_type="LAB",scope_id="other-lab",
            schema_record_id=schema["schema_record_id"],actor="owner",
        )
    with pytest.raises(ConfigurationProfileNotFound):
        service.create_profile(
            project_id="project-1",name="Unknown device",description="",scope_type="DEVICE",scope_id="ap-2",
            schema_record_id=schema["schema_record_id"],actor="owner",device_exists=False,
        )
