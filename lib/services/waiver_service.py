from __future__ import annotations
from datetime import datetime,timezone
from lib.domain import ReleaseWaiver,WaiverScope
from lib.repositories import SQLiteDatabase,SQLiteWaiverRepository,SQLiteEventRepository,SQLiteRunRepository
from .run_service import generate_ulid

class WaiverService:
    def __init__(self,repository,event_repository,run_repository):
        self.repository=repository;self.event_repository=event_repository;self.run_repository=run_repository
    @classmethod
    def from_sqlite(cls,database):
        return cls(SQLiteWaiverRepository(database),SQLiteEventRepository(database),SQLiteRunRepository(database))
    def create(self,*,scope:WaiverScope,target_id:str,issue_code:str,reason:str,created_by:str,expires_at=None,audit_reference=None):
        if not reason.strip() or not created_by.strip(): raise ValueError("waiver reason and creator are required")
        waiver=ReleaseWaiver(generate_ulid(),scope,target_id,issue_code.strip(),reason.strip(),created_by.strip(),datetime.now(timezone.utc),expires_at,audit_reference or generate_ulid(),True)
        self.repository.save(waiver)
        if self.run_repository.get(target_id) is not None:
            from lib.domain import LifecycleEvent
            self.event_repository.append(LifecycleEvent(generate_ulid(),target_id,"WAIVER_CREATED",waiver.created_at,details={"waiver_id":waiver.waiver_id,"issue_code":waiver.issue_code,"scope":waiver.scope.value,"created_by":waiver.created_by}))
        return waiver
    def active_for(self,target_id:str):
        return [w for w in self.repository.list_active(target_id) if w.is_active()]
