from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from .run_service import repository_commit
from .test_registry import TestRegistry

@dataclass(frozen=True,slots=True)
class ReproductionManifest:
    manifest_version:str
    run_id:str
    firmware_version:str
    lab_id:str
    repository_commit:str
    configuration_hash:str
    selected_tests:tuple[str,...]
    test_definition_versions:dict[str,str]
    validation_profile:str
    environment_fingerprint:str|None
    manifest_path:Path

class ReproductionManifestService:
    def __init__(self,*,test_registry:TestRegistry,root:str|Path):
        self.test_registry=test_registry;self.root=Path(root)
    def create(self,run_id:str,run,output_dir:str|Path|None=None)->ReproductionManifest:
        versions=dict(run.test_definition_versions)
        payload={"manifest_version":"netregress-reproduction.v1","run_id":run_id,"firmware_version":run.firmware_version,"lab_id":run.lab_id,"repository_commit":run.repository_commit or repository_commit(str(self.root)),"configuration_hash":run.configuration_hash,"selected_tests":list(run.selected_tests),"test_definition_versions":versions,"validation_profile":run.validation_profile,"environment_fingerprint":getattr(run.environment,"tools",{}).get("fingerprint") if run.environment else None,"resolved_config":dict(run.resolved_config)}
        out=Path(output_dir or self.root/"results"/"reproduction");out.mkdir(parents=True,exist_ok=True)
        path=out/f"{run_id}.json";path.write_text(json.dumps(payload,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        return ReproductionManifest("netregress-reproduction.v1",run_id,run.firmware_version,run.lab_id,payload["repository_commit"],run.configuration_hash,tuple(run.selected_tests),versions,run.validation_profile,payload["environment_fingerprint"],path)
