from __future__ import annotations

import pytest

from lib.repositories import SQLiteDatabase
from lib.services.configuration_schema_registry import (
    ConfigurationSchemaError,
    ConfigurationSchemaNotFound,
    ConfigurationSchemaRegistry,
)


@pytest.fixture
def registry(tmp_path):
    database=SQLiteDatabase(tmp_path/"schemas.sqlite")
    database.initialize()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at)
               VALUES('org-1','org','Organization','ACTIVE','2026-11-13T00:00:00+00:00','2026-11-13T00:00:00+00:00')"""
        )
        connection.execute(
            """INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at)
               VALUES('project-1','org-1','project','Project','ACTIVE','2026-11-13T00:00:00+00:00','2026-11-13T00:00:00+00:00')"""
        )
    return database,ConfigurationSchemaRegistry(database)


def schema_definition():
    return {
        "type":"object",
        "required":["ssid","channel"],
        "additionalProperties":False,
        "properties":{
            "ssid":{"type":"string","minLength":1,"maxLength":32},
            "channel":{"type":"integer","minimum":1,"maximum":165},
            "enabled":{"type":"boolean"},
            "mode":{"type":"string","enum":["11n","11ac","11ax"]},
            "dns":{"type":"array","items":{"type":"string"},"minItems":1},
        },
    }


def test_registers_and_reads_versioned_project_schema(registry):
    _database,service=registry
    item=service.register(
        project_id="project-1",schema_id="wifi.access_point",version=1,
        name="Access Point Configuration",definition=schema_definition(),actor="owner",
    )
    assert item["version"]==1
    assert service.get("project-1","wifi.access_point")["schema_record_id"]==item["schema_record_id"]
    assert service.list("project-1")[0]["schema_id"]=="wifi.access_point"
    assert service.get("another-project","wifi.access_point") is None


def test_validates_typed_values_and_required_fields(registry):
    _database,service=registry
    service.register(
        project_id="project-1",schema_id="wifi.access_point",version=1,
        name="Access Point",definition=schema_definition(),actor="owner",
    )
    valid=service.validate(
        "project-1","wifi.access_point",1,
        {"ssid":"NetRegress","channel":36,"enabled":True,"mode":"11ax","dns":["1.1.1.1"]},
    )
    assert valid["valid"] is True
    invalid=service.validate(
        "project-1","wifi.access_point",1,
        {"ssid":"","channel":200,"enabled":"yes","extra":"no"},
    )
    assert invalid["valid"] is False
    assert {item["path"] for item in invalid["errors"]} >= {
        "$.ssid","$.channel","$.enabled","$.extra",
    }


def test_rejects_secret_fields_and_unbounded_object_shapes(registry):
    _database,service=registry
    secret_schema={"type":"object","properties":{"password":{"type":"string"}}}
    with pytest.raises(ConfigurationSchemaError,match="sensitive"):
        service.register(
            project_id="project-1",schema_id="network.auth",version=1,
            name="Unsafe",definition=secret_schema,actor="owner",
        )
    open_schema={"type":"object","additionalProperties":True,"properties":{}}
    with pytest.raises(ConfigurationSchemaError,match="additionalProperties"):
        service.register(
            project_id="project-1",schema_id="network.open",version=1,
            name="Unsafe",definition=open_schema,actor="owner",
        )


def test_requires_sequential_schema_versions(registry):
    _database,service=registry
    definition=schema_definition()
    with pytest.raises(ConfigurationSchemaError,match="next version"):
        service.register(
            project_id="project-1",schema_id="wifi.access_point",version=2,
            name="Access Point",definition=definition,actor="owner",
        )
    service.register(
        project_id="project-1",schema_id="wifi.access_point",version=1,
        name="Access Point",definition=definition,actor="owner",
    )
    updated=service.register(
        project_id="project-1",schema_id="wifi.access_point",version=2,
        name="Access Point",definition=definition,actor="owner",
    )
    assert updated["version"]==2


def test_schema_errors_and_not_found_are_explicit(registry):
    _database,service=registry
    with pytest.raises(ConfigurationSchemaNotFound):
        service.validate("project-1","missing",1,{})
    with pytest.raises(ConfigurationSchemaError,match="schema_id"):
        service.register(
            project_id="project-1",schema_id="Invalid ID",version=1,
            name="Bad",definition=schema_definition(),actor="owner",
        )
