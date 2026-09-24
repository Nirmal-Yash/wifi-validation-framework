from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import json, os
from typing import Sequence
from werkzeug.security import check_password_hash, generate_password_hash
class Role(str,Enum): OWNER="OWNER"; ADMIN="ADMIN"; OPERATOR="OPERATOR"; VIEWER="VIEWER"
class AuthConfigurationError(RuntimeError): pass
@dataclass(frozen=True,slots=True)
class UserRecord:
    username:str; password_hash:str; role:Role; projects:tuple[str,...]=("*",)
    def can_access_project(self,project_id): return project_id is None or "*" in self.projects or project_id in self.projects
@dataclass(frozen=True,slots=True)
class AuthenticatedUser: username:str; role:Role; projects:tuple[str,...]
class AuthManager:
    def __init__(self,users:Sequence[UserRecord],*,required=True): self._users={u.username:u for u in users}; self.required=required
    @classmethod
    def from_env(cls):
        required=os.getenv("NETREGRESS_AUTH_REQUIRED","1").lower() not in {"0","false","no"}; raw=os.getenv("NETREGRESS_AUTH_USERS_JSON","").strip()
        if not raw: return cls((),required=required)
        try: items=json.loads(raw)
        except json.JSONDecodeError as exc: raise AuthConfigurationError("NETREGRESS_AUTH_USERS_JSON is not valid JSON") from exc
        if not isinstance(items,list): raise AuthConfigurationError("NETREGRESS_AUTH_USERS_JSON must be an array")
        return cls([UserRecord(str(x["username"]),str(x["password_hash"]),Role(str(x["role"]).upper()),tuple(x.get("projects") or ("*",))) for x in items],required=required)
    @staticmethod
    def password_hash(password): return generate_password_hash(password,method="scrypt")
    def authenticate(self,username,password):
        u=self._users.get(username)
        return AuthenticatedUser(u.username,u.role,u.projects) if u and check_password_hash(u.password_hash,password) else None
    def require_configured(self):
        if self.required and not self._users: raise AuthConfigurationError("authentication is enabled but no users are configured")
    @staticmethod
    def authorize(user,action,project_id=None):
        if not user.can_access_project(project_id): return False
        return {"view":True,"execute":user.role in {Role.OWNER,Role.ADMIN,Role.OPERATOR},"admin":user.role in {Role.OWNER,Role.ADMIN},"owner":user.role is Role.OWNER}.get(action,False)
