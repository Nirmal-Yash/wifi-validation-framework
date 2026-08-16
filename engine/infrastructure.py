from __future__ import annotations
from dataclasses import dataclass,field
from typing import Protocol

@dataclass(frozen=True)
class InfrastructureTarget:
    name:str
    mode:str='tier1'
    management_address:str|None=None
    metadata:dict=field(default_factory=dict)

class InfrastructureAdapter(Protocol):
    target:InfrastructureTarget
    def preflight(self)->dict: ...
    def provision(self)->dict: ...
    def collect(self)->dict: ...
    def teardown(self)->dict: ...

class LocalTier1Adapter:
    """Adapter for the Linux/mac80211_hwsim lab. It deliberately performs no
    privileged action itself; preflight reports what the test runner needs."""
    def __init__(self,target:InfrastructureTarget): self.target=target
    def preflight(self):
        import os,shutil
        return {'ready':bool(shutil.which('ip') and shutil.which('wpa_supplicant')),'mode':'tier1','root':os.geteuid()==0,'required_tools':{'ip':bool(shutil.which('ip')),'wpa_supplicant':bool(shutil.which('wpa_supplicant')),'hostapd':bool(shutil.which('hostapd')),'radiusd':bool(shutil.which('radiusd') or shutil.which('freeradius'))}}
    def provision(self): return {'status':'delegated','message':'Tier-1 provisioning remains owned by the live test fixture and privileged host.'}
    def collect(self): return {'status':'ready'}
    def teardown(self): return {'status':'delegated'}

class PhysicalLabAdapter:
    """Safe Tier-2 abstraction. Network changes are intentionally not executed
    until a concrete adapter is configured by the deployment owner."""
    def __init__(self,target:InfrastructureTarget): self.target=target
    def preflight(self): return {'ready':False,'mode':'tier2','message':'No physical-lab adapter configured; refusing implicit device changes.'}
    def provision(self): raise RuntimeError('Tier-2 physical provisioning requires an explicit infrastructure adapter')
    def collect(self): raise RuntimeError('Tier-2 physical collection requires an explicit infrastructure adapter')
    def teardown(self): return {'status':'noop'}

def adapter_for(mode='tier1',**kwargs)->InfrastructureAdapter:
    target=InfrastructureTarget(name=kwargs.get('name','default'),mode=mode,management_address=kwargs.get('management_address'),metadata=kwargs)
    if mode=='tier1': return LocalTier1Adapter(target)
    if mode=='tier2': return PhysicalLabAdapter(target)
    raise ValueError(f'Unsupported infrastructure mode: {mode}')
