from __future__ import annotations

import sqlite3

import pytest

from lib.domain.models import Metric,Sample
from lib.repositories import SQLiteDatabase
from lib.services.performance_policy_service import (
    PerformancePolicyEngine,PerformancePolicyError,PerformancePolicyNotFound,PerformancePolicyService,
)


@pytest.fixture
def policies(tmp_path):
    database=SQLiteDatabase(tmp_path/"policies.sqlite")
    database.initialize()
    now="2026-11-13T00:00:00+00:00"
    with database.transaction(immediate=True) as connection:
        connection.execute("INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                           ("org-1","org","Organization","ACTIVE",now,now))
        connection.execute("INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                           ("project-1","org-1","project","Project","ACTIVE",now,now))
        connection.execute("INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                           ("lab-1","project-1","Lab","gns3",1,"ACTIVE",now,now))
    return database,PerformancePolicyService(database)


def definition():
    return {"metrics":[
        {"name":"wifi.latency","unit":"ms","direction":"LOWER_IS_BETTER","target":20,"warning":40,"failure":80,
         "aggregate":"p95","minimum_samples":3,"allowed_statuses":["VALID"],"include_retried":False,"required":True},
        {"name":"wifi.throughput","unit":"Mbps","direction":"HIGHER_IS_BETTER","target":100,"warning":80,"failure":50,
         "aggregate":"mean","minimum_samples":2,"required":False},
    ]}


def test_threshold_validation_and_direction_ordering():
    normalized=PerformancePolicyEngine.normalize_definition(definition())
    assert normalized["metrics"][0]["aggregate"]=="p95"
    invalid=definition()
    invalid["metrics"][0]["target"]=90
    with pytest.raises(PerformancePolicyError,match="target <= warning <= failure"):
        PerformancePolicyEngine.normalize_definition(invalid)
    invalid=definition()
    invalid["metrics"][1]["warning"]=120
    with pytest.raises(PerformancePolicyError,match="target >= warning >= failure"):
        PerformancePolicyEngine.normalize_definition(invalid)


def test_engine_uses_existing_measurement_evaluator_and_returns_thresholds():
    metrics=[
        Metric("wifi.latency","ms",(
            Sample(10),Sample(22),Sample(25),Sample(100,warmup=True),Sample(999,retried=True),
        )),
        Metric("wifi.throughput","Mbps",(Sample(90),Sample(95))),
    ]
    evaluated=PerformancePolicyEngine.evaluate(definition(),metrics)
    latency=evaluated["metrics"][0]
    throughput=evaluated["metrics"][1]
    assert latency["outcome"]=="WARNING"
    assert latency["sample_count"]==3
    assert latency["decision_value"]>20
    assert throughput["outcome"]=="WARNING"
    assert evaluated["overall"]=="WARNING"
    assert evaluated["effective_thresholds"][0]["failure"]==80


def test_missing_and_unit_mismatch_never_report_pass():
    no_samples=PerformancePolicyEngine.evaluate(definition(),[])
    assert no_samples["overall"]=="WARNING"
    assert no_samples["metrics"][0]["outcome"]=="INSUFFICIENT_DATA"
    mismatch=PerformancePolicyEngine.evaluate(
        definition(),[Metric("wifi.latency","seconds",(Sample(0.01),Sample(0.02),Sample(0.03)))]
    )
    assert mismatch["metrics"][0]["outcome"]=="INVALID_DATA"


def test_profile_revision_publish_assign_and_evaluate_are_project_scoped(policies):
    database,service=policies
    profile=service.create_profile(project_id="project-1",name="WiFi Gold",scope_type="LAB",scope_id="lab-1",actor="owner")
    revision=service.create_revision(profile["policy_profile_id"],definition=definition(),actor="owner")
    assert revision["status"]=="DRAFT" and len(revision["policy_hash"])==64
    published=service.publish(profile["policy_profile_id"],revision["revision_id"],actor="owner")
    assert published["status"]=="PUBLISHED"
    assignment=service.assign(profile["policy_profile_id"],revision["revision_id"],lab_id="lab-1",actor="owner")
    assert assignment["lab_id"]=="lab-1"
    result=service.evaluate(revision["revision_id"],[Metric("wifi.latency","ms",(Sample(5),Sample(10),Sample(12)))])
    assert result["overall"]=="PASS"
    assert service.list_assignments("another-project")==[]
    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError,match="revision content is immutable"):
            connection.execute("UPDATE performance_policy_revisions SET policy_json='{}' WHERE revision_id=?",(revision["revision_id"],))


def test_published_and_project_scope_rules(policies):
    _database,service=policies
    profile=service.create_profile(project_id="project-1",name="Project Policy",scope_type="PROJECT",actor="owner")
    revision=service.create_revision(profile["policy_profile_id"],definition=definition(),actor="owner")
    with pytest.raises(PerformancePolicyError,match="only published"):
        service.assign(profile["policy_profile_id"],revision["revision_id"],lab_id="lab-1",actor="owner")
    service.publish(profile["policy_profile_id"],revision["revision_id"],actor="owner")
    assignment=service.assign(profile["policy_profile_id"],revision["revision_id"],lab_id="lab-1",actor="owner")
    assert assignment["policy_profile_id"]==profile["policy_profile_id"]
    with pytest.raises(PerformancePolicyNotFound):
        service.assign(profile["policy_profile_id"],revision["revision_id"],lab_id="foreign-lab",actor="owner")
