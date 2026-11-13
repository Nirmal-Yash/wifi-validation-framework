"""Versioned threshold profiles using the canonical measurement evaluator."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import secrets
from typing import Any, Mapping, Sequence

from lib.domain.models import Metric, Sample
from lib.domain.statistics import (
    InsufficientSamplesError, MeasurementPolicy, MeasurementPolicyEvaluator, StatisticKind,
)


class PerformancePolicyError(ValueError):
    """Invalid policy definition or lifecycle transition."""


class PerformancePolicyNotFound(LookupError):
    """Policy profile, revision or target not found in the current Project."""


class PerformancePolicyEngine:
    DIRECTIONS=frozenset({"LOWER_IS_BETTER","HIGHER_IS_BETTER"})
    ALLOWED_STATUSES=frozenset({"VALID","INVALID","MISSING","SUSPECT","ERROR"})

    @classmethod
    def normalize_definition(cls,definition:object)->dict:
        if not isinstance(definition,Mapping): raise PerformancePolicyError("policy definition must be an object")
        if set(definition)!={"metrics"}: raise PerformancePolicyError("policy definition must contain only a metrics array")
        items=definition.get("metrics")
        if not isinstance(items,list) or not items: raise PerformancePolicyError("metrics must be a non-empty array")
        normalized=[]; names=set()
        for index,item in enumerate(items):
            path=f"metrics[{index}]"
            if not isinstance(item,Mapping): raise PerformancePolicyError(f"{path} must be an object")
            name=str(item.get("name","")).strip()
            unit=str(item.get("unit","")).strip()
            direction=str(item.get("direction","")).strip().upper()
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,127}",name): raise PerformancePolicyError(f"{path}.name is invalid")
            if name in names: raise PerformancePolicyError(f"duplicate metric definition: {name}")
            names.add(name)
            if not unit or len(unit)>32: raise PerformancePolicyError(f"{path}.unit is required")
            if direction not in cls.DIRECTIONS: raise PerformancePolicyError(f"{path}.direction is invalid")
            thresholds={}
            for key in ("target","warning","failure"):
                value=item.get(key)
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(float(value)):
                    raise PerformancePolicyError(f"{path}.{key} must be a finite number")
                thresholds[key]=float(value)
            if direction=="LOWER_IS_BETTER":
                if not thresholds["target"]<=thresholds["warning"]<=thresholds["failure"]:
                    raise PerformancePolicyError(f"{path} lower-is-better thresholds require target <= warning <= failure")
            elif not thresholds["target"]>=thresholds["warning"]>=thresholds["failure"]:
                raise PerformancePolicyError(f"{path} higher-is-better thresholds require target >= warning >= failure")
            try: aggregate=StatisticKind(str(item.get("aggregate","mean")).lower())
            except ValueError as exc: raise PerformancePolicyError(f"{path}.aggregate is unsupported") from exc
            minimum=item.get("minimum_samples",3)
            if isinstance(minimum,bool) or not isinstance(minimum,int) or minimum<1 or minimum>100000:
                raise PerformancePolicyError(f"{path}.minimum_samples must be an integer from 1 to 100000")
            statuses=item.get("allowed_statuses",["VALID"])
            if not isinstance(statuses,list) or not statuses or any(not isinstance(s,str) or s.upper() not in cls.ALLOWED_STATUSES for s in statuses):
                raise PerformancePolicyError(f"{path}.allowed_statuses must contain supported metric statuses")
            if len(set(s.upper() for s in statuses))!=len(statuses): raise PerformancePolicyError(f"{path}.allowed_statuses cannot contain duplicates")
            include_retried=item.get("include_retried",False)
            required=item.get("required",True)
            if not isinstance(include_retried,bool) or not isinstance(required,bool):
                raise PerformancePolicyError(f"{path}.include_retried and required must be booleans")
            normalized.append({
                "name":name,"unit":unit,"direction":direction,**thresholds,
                "aggregate":aggregate.value,"minimum_samples":minimum,
                "allowed_statuses":[s.upper() for s in statuses],
                "include_retried":include_retried,"required":required,
            })
        return {"metrics":normalized}

    @classmethod
    def evaluate(cls,definition:Mapping[str,Any],metrics:Sequence[Metric])->dict:
        policy=cls.normalize_definition(definition)
        by_name={}
        for metric in metrics:
            if not isinstance(metric,Metric): raise PerformancePolicyError("metrics must contain Metric domain objects")
            if metric.name in by_name: raise PerformancePolicyError(f"duplicate collected metric: {metric.name}")
            by_name[metric.name]=metric
        results=[]
        for spec in policy["metrics"]:
            metric=by_name.get(spec["name"])
            if metric is None:
                outcome="INSUFFICIENT_DATA" if spec["required"] else "NOT_REQUIRED"
                results.append({"metric_name":spec["name"],"unit":spec["unit"],"outcome":outcome,
                                "reason":"Required metric was not collected." if spec["required"] else "Optional metric was not collected.",
                                "sample_count":0,"thresholds":{key:spec[key] for key in ("direction","target","warning","failure")}})
                continue
            if metric.unit!=spec["unit"]:
                results.append({"metric_name":spec["name"],"unit":metric.unit,"outcome":"INVALID_DATA",
                                "reason":f"Metric unit mismatch; expected {spec['unit']}.","sample_count":0,
                                "thresholds":{key:spec[key] for key in ("direction","target","warning","failure")}})
                continue
            measurement=MeasurementPolicy(
                aggregate=StatisticKind(spec["aggregate"]),minimum_samples=spec["minimum_samples"],
                allowed_statuses=tuple(spec["allowed_statuses"]),include_retried=spec["include_retried"],
            )
            try:
                summary=MeasurementPolicyEvaluator.evaluate(metric,measurement)
            except InsufficientSamplesError as exc:
                results.append({"metric_name":spec["name"],"unit":spec["unit"],"outcome":"INSUFFICIENT_DATA",
                                "reason":str(exc),"sample_count":sum(
                                    1 for sample in metric.samples if not sample.warmup
                                    and sample.status in spec["allowed_statuses"]
                                    and (spec["include_retried"] or not sample.retried)
                                ),"thresholds":{key:spec[key] for key in ("direction","target","warning","failure")}})
                continue
            value=summary.decision_value
            if spec["direction"]=="LOWER_IS_BETTER":
                outcome="PASS" if value<=spec["target"] else "WARNING" if value<=spec["warning"] else "FAIL"
                critical=value>spec["failure"]
            else:
                outcome="PASS" if value>=spec["target"] else "WARNING" if value>=spec["warning"] else "FAIL"
                critical=value<spec["failure"]
            results.append({
                "metric_name":spec["name"],"unit":spec["unit"],"outcome":outcome,
                "reason":f"{spec['aggregate']}={value:g} {spec['unit']}; target {spec['target']:g}, warning {spec['warning']:g}, failure {spec['failure']:g}.",
                "decision_value":value,"sample_count":summary.count,
                "thresholds":{key:spec[key] for key in ("direction","target","warning","failure")},
                "critical":critical,"aggregate":spec["aggregate"],
            })
        states={item["outcome"] for item in results}
        overall="FAIL" if "FAIL" in states or "INVALID_DATA" in states else "WARNING" if "WARNING" in states or "INSUFFICIENT_DATA" in states else "PASS"
        if all(state=="NOT_REQUIRED" for state in states): overall="NOT_EVALUATED"
        return {"overall":overall,"metrics":results,"effective_thresholds":policy["metrics"]}


class PerformancePolicyService:
    def __init__(self,database,engine:PerformancePolicyEngine|None=None)->None:
        self.database=database
        self.engine=engine or PerformancePolicyEngine()

    @staticmethod
    def _now()->str: return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _audit(connection,actor,action,resource_type,resource_id,details):
        connection.execute(
            """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
               VALUES(?,?,?,?,?,?,?)""",
            ("AUD-"+secrets.token_hex(12),actor,action,resource_type,resource_id,
             json.dumps(details,sort_keys=True,separators=(",",":")),PerformancePolicyService._now()),
        )

    @staticmethod
    def _profile(row)->dict:
        return {key:row[key] for key in ("policy_profile_id","project_id","name","description","scope_type","scope_id","status","created_at","updated_at","created_by","updated_by")}

    @staticmethod
    def _revision(row)->dict:
        return {key:row[key] for key in ("revision_id","policy_profile_id","revision_number","policy_hash","status","created_at","created_by","published_at","published_by")}|{"definition":json.loads(row["policy_json"])}

    def get_profile(self,profile_id):
        with self.database.connection() as connection:
            row=connection.execute("SELECT * FROM performance_policy_profiles WHERE policy_profile_id=?",(profile_id,)).fetchone()
        return self._profile(row) if row is not None else None

    def list_profiles(self,project_id):
        with self.database.connection() as connection:
            rows=connection.execute("SELECT * FROM performance_policy_profiles WHERE project_id=? ORDER BY scope_type,scope_id,name",(project_id,)).fetchall()
        return [self._profile(row) for row in rows]

    def create_profile(self,*,project_id,name,description="",scope_type="PROJECT",scope_id=None,actor):
        project_id=str(project_id or "").strip();name=str(name or "").strip()
        scope_type=str(scope_type or "").upper();actor=str(actor or "").strip()
        if not project_id or not name or len(name)>120 or not actor: raise PerformancePolicyError("Project, profile name and actor are required")
        if scope_type not in {"PROJECT","LAB"}: raise PerformancePolicyError("scope_type must be PROJECT or LAB")
        if scope_type=="PROJECT": scope_id=project_id
        else:
            scope_id=str(scope_id or "").strip()
            with self.database.connection() as connection:
                lab=connection.execute("SELECT project_id FROM labs WHERE lab_id=?",(scope_id,)).fetchone()
            if lab is None or lab["project_id"]!=project_id: raise PerformancePolicyNotFound("Lab not found in this Project")
        now=self._now();profile_id="ppf_"+secrets.token_hex(12)
        with self.database.transaction(immediate=True) as connection:
            try:
                connection.execute(
                    """INSERT INTO performance_policy_profiles(
                       policy_profile_id,project_id,name,description,scope_type,scope_id,status,
                       created_at,updated_at,created_by,updated_by)
                       VALUES(?,?,?,?,?,?,'ACTIVE',?,?,?,?)""",
                    (profile_id,project_id,name,str(description or "")[:500],scope_type,scope_id,now,now,actor,actor),
                )
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc): raise PerformancePolicyError("a policy profile with this name already exists at the selected scope") from exc
                raise
            self._audit(connection,actor,"PERFORMANCE_POLICY_PROFILE_CREATED","PERFORMANCE_POLICY_PROFILE",profile_id,
                        {"project_id":project_id,"scope_type":scope_type,"scope_id":scope_id})
        return self.get_profile(profile_id)

    def list_revisions(self,profile_id):
        with self.database.connection() as connection:
            rows=connection.execute("SELECT * FROM performance_policy_revisions WHERE policy_profile_id=? ORDER BY revision_number DESC",(profile_id,)).fetchall()
        return [self._revision(row) for row in rows]

    def get_revision(self,revision_id):
        with self.database.connection() as connection:
            row=connection.execute("SELECT * FROM performance_policy_revisions WHERE revision_id=?",(revision_id,)).fetchone()
        return self._revision(row) if row is not None else None

    def create_revision(self,profile_id,*,definition,actor):
        profile=self.get_profile(profile_id)
        if profile is None: raise PerformancePolicyNotFound("performance policy profile not found")
        if profile["status"]!="ACTIVE": raise PerformancePolicyError("archived profiles cannot receive revisions")
        normalized=self.engine.normalize_definition(definition)
        policy_json=json.dumps(normalized,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
        digest=hashlib.sha256(policy_json.encode("utf-8")).hexdigest()
        revision_id="ppr_"+secrets.token_hex(12);now=self._now()
        with self.database.transaction(immediate=True) as connection:
            number=int(connection.execute("SELECT COALESCE(MAX(revision_number),0)+1 FROM performance_policy_revisions WHERE policy_profile_id=?",(profile_id,)).fetchone()[0])
            connection.execute(
                """INSERT INTO performance_policy_revisions(
                   revision_id,policy_profile_id,revision_number,policy_json,policy_hash,status,
                   created_at,created_by,published_at,published_by)
                   VALUES(?,?,?,?,?,'DRAFT',?,?,NULL,NULL)""",
                (revision_id,profile_id,number,policy_json,digest,now,actor),
            )
            self._audit(connection,actor,"PERFORMANCE_POLICY_REVISION_CREATED","PERFORMANCE_POLICY_REVISION",revision_id,
                        {"profile_id":profile_id,"revision_number":number,"policy_hash":digest})
        return self.get_revision(revision_id)

    def publish(self,profile_id,revision_id,*,actor):
        profile=self.get_profile(profile_id);revision=self.get_revision(revision_id)
        if profile is None or revision is None or revision["policy_profile_id"]!=profile_id:
            raise PerformancePolicyNotFound("policy profile or revision not found")
        if revision["status"]!="DRAFT": raise PerformancePolicyError("only draft policy revisions can be published")
        now=self._now()
        with self.database.transaction(immediate=True) as connection:
            cursor=connection.execute(
                "UPDATE performance_policy_revisions SET status='PUBLISHED',published_at=?,published_by=? WHERE revision_id=? AND status='DRAFT'",
                (now,actor,revision_id),
            )
            if cursor.rowcount!=1: raise PerformancePolicyError("policy revision changed during publish")
            self._audit(connection,actor,"PERFORMANCE_POLICY_REVISION_PUBLISHED","PERFORMANCE_POLICY_REVISION",revision_id,
                        {"profile_id":profile_id,"policy_hash":revision["policy_hash"]})
        return self.get_revision(revision_id)

    def assign(self,profile_id,revision_id,*,lab_id,actor):
        profile=self.get_profile(profile_id);revision=self.get_revision(revision_id)
        if profile is None or revision is None or revision["policy_profile_id"]!=profile_id:
            raise PerformancePolicyNotFound("policy profile or revision not found")
        if revision["status"]!="PUBLISHED": raise PerformancePolicyError("only published policy revisions can be assigned")
        with self.database.connection() as connection:
            lab=connection.execute("SELECT project_id FROM labs WHERE lab_id=?",(lab_id,)).fetchone()
        if lab is None or lab["project_id"]!=profile["project_id"]: raise PerformancePolicyNotFound("Lab not found in this Project")
        if profile["scope_type"] not in {"PROJECT","LAB"} or (profile["scope_type"]=="LAB" and profile["scope_id"]!=lab_id):
            raise PerformancePolicyError("policy profile scope is incompatible with the selected Lab")
        now=self._now();assignment_id="ppa_"+secrets.token_hex(12)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO performance_policy_assignments(
                   assignment_id,project_id,lab_id,policy_profile_id,revision_id,assigned_at,assigned_by)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(project_id,lab_id) DO UPDATE SET
                   assignment_id=excluded.assignment_id,policy_profile_id=excluded.policy_profile_id,
                   revision_id=excluded.revision_id,assigned_at=excluded.assigned_at,assigned_by=excluded.assigned_by""",
                (assignment_id,profile["project_id"],lab_id,profile_id,revision_id,now,actor),
            )
            self._audit(connection,actor,"PERFORMANCE_POLICY_ASSIGNED","PERFORMANCE_POLICY_ASSIGNMENT",assignment_id,
                        {"project_id":profile["project_id"],"lab_id":lab_id,"revision_id":revision_id})
        return {"assignment_id":assignment_id,"project_id":profile["project_id"],"lab_id":lab_id,
                "policy_profile_id":profile_id,"revision_id":revision_id,"assigned_at":now,"assigned_by":actor}

    def list_assignments(self,project_id):
        with self.database.connection() as connection:
            rows=connection.execute("SELECT * FROM performance_policy_assignments WHERE project_id=? ORDER BY lab_id",(project_id,)).fetchall()
        return [{key:row[key] for key in row.keys()} for row in rows]

    def evaluate(self,revision_id,metrics:Sequence[Metric])->dict:
        revision=self.get_revision(revision_id)
        if revision is None: raise PerformancePolicyNotFound("performance policy revision not found")
        if revision["status"]!="PUBLISHED": raise PerformancePolicyError("only published policy revisions can be evaluated")
        result=self.engine.evaluate(revision["definition"],metrics)
        return {"revision_id":revision_id,"policy_hash":revision["policy_hash"],**result}
