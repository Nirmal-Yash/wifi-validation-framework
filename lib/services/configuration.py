from __future__ import annotations
from dataclasses import dataclass
import hashlib,json,os
from typing import Any,Mapping
@dataclass(frozen=True,slots=True)
class ResolvedConfiguration:
    values:Mapping[str,Any]; configuration_hash:str; provenance:Mapping[str,tuple[str,...]]
class ConfigurationResolver:
    PRECEDENCE=("defaults","environment","lab","device","run","test_override")
    def resolve(self,**sources):
        merged={}; prov={}
        def merge(dst,src,name,prefix=""):
            for k,v in (src or {}).items():
                key=f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v,Mapping) and isinstance(dst.get(k),Mapping):
                    nested=dict(dst[k]); merge(nested,v,name,key); dst[k]=nested
                else: dst[k]=v
                prov.setdefault(key,[]).append(name)
        for name in self.PRECEDENCE: merge(merged,sources.get(name),name)
        digest=hashlib.sha256(json.dumps(merged,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return ResolvedConfiguration(merged,digest,{k:tuple(v) for k,v in prov.items()})
    @staticmethod
    def environment_json():
        value=json.loads(os.getenv("NETREGRESS_CONFIG_JSON","{}") or "{}")
        if not isinstance(value,Mapping): raise ValueError("NETREGRESS_CONFIG_JSON must be an object")
        return value
