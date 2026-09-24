from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import json,zipfile
from pathlib import Path
from typing import Any,Iterable,Mapping
from lib.domain import ArtifactType
from .artifact_service import ArtifactService
from .run_service import generate_ulid,redact_configuration

@dataclass(frozen=True,slots=True)
class DiagnosticBundle:
    bundle_id:str
    manifest_path:Path
    archive_path:Path|None
    sha256:str

class DiagnosticBundleService:
    def __init__(self,*,artifact_service:ArtifactService,results_root:str|Path,clock=lambda:datetime.now(timezone.utc)):
        self.artifact_service=artifact_service;self.results_root=Path(results_root);self.clock=clock
    def build(self,*,run_id:str,reason:str,extra:Mapping[str,Any]|None=None)->DiagnosticBundle:
        run=self.artifact_service.run_repository.get(run_id)
        if run is None: raise ValueError(f"Run not found: {run_id}")
        events=self.artifact_service.event_repository.list_for_run(run_id)
        artifacts=self.artifact_service.list_for_run(run_id)
        manifest={
            "schema_version":"netregress-diagnostic.v1",
            "bundle_id":generate_ulid(),
            "created_at":self.clock().isoformat(),
            "run_id":run_id,
            "reason":reason,
            "run":{"display_id":run.display_id,"lifecycle":run.lifecycle.value,"outcome":run.outcome.value if run.outcome else None,"failure_class":getattr(run,"failure_class",None).value if getattr(run,"failure_class",None) else None,"failure_reason":getattr(run,"failure_reason",None),"configuration_hash":run.configuration_hash,"repository_commit":run.repository_commit,"resolved_config":redact_configuration(run.resolved_config)},
            "artifacts":[{"artifact_id":a.artifact_id,"type":a.artifact_type.value,"path":a.path,"size_bytes":a.size_bytes,"sha256":a.sha256,"evidence_state":a.evidence_state.value,"display_name":a.display_name} for a in artifacts if a.soft_deleted_at is None],
            "events":[{"event_id":e.event_id,"event_type":e.event_type,"occurred_at":e.occurred_at.isoformat(),"details":dict(e.details)} for e in events],
            "extra":dict(extra or {}),
        }
        out_dir=self.results_root/"diagnostics"/run_id;out_dir.mkdir(parents=True,exist_ok=True)
        manifest_path=out_dir/"manifest.json";manifest_path.write_text(json.dumps(manifest,sort_keys=True,indent=2)+"
",encoding="utf-8")
        archive_path=out_dir/f"{manifest['bundle_id']}.zip"
        with zipfile.ZipFile(archive_path,"w",compression=zipfile.ZIP_DEFLATED) as z:
            z.write(manifest_path,arcname="manifest.json")
            for a in artifacts:
                if a.soft_deleted_at is not None: continue
                p=Path(a.path)
                if p.is_file() and self.artifact_service.verify(a.artifact_id):
                    try:z.write(p,arcname=f"artifacts/{a.display_name}")
                    except ValueError: pass
        import hashlib
        digest=hashlib.sha256(archive_path.read_bytes()).hexdigest()
        self.artifact_service.register_file(run_id=run_id,path=archive_path,artifact_type=ArtifactType.DIAGNOSTIC_BUNDLE,display_name=archive_path.name,expected_sha256=digest,sensitivity_class="INTERNAL")
        return DiagnosticBundle(manifest["bundle_id"],manifest_path,archive_path,digest)
