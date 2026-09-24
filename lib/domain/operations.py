from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

class FailureClass(str,Enum):
    PRODUCT_FAILED="PRODUCT_FAILED"
    LAB_FAILED="LAB_FAILED"
    RUNNER_DISCONNECTED="RUNNER_DISCONNECTED"
    WORKER_CRASHED="WORKER_CRASHED"
    TIMED_OUT="TIMED_OUT"
    CANCELLED="CANCELLED"
    ABORTED="ABORTED"

class WaiverScope(str,Enum):
    TEST="TEST"
    RUN="RUN"
    REGRESSION="REGRESSION"
    RELEASE="RELEASE"

@dataclass(frozen=True,slots=True)
class ReleaseWaiver:
    waiver_id:str
    scope:WaiverScope
    target_id:str
    issue_code:str
    reason:str
    created_by:str
    created_at:datetime
    expires_at:datetime|None=None
    audit_reference:str=""
    active:bool=True
    def is_active(self,now:datetime|None=None)->bool:
        if not self.active: return False
        current=now or datetime.now(timezone.utc)
        return self.expires_at is None or current < self.expires_at
