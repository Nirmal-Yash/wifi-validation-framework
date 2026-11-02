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
    def can_access_project(self,project_id): return "*" in self.projects or (project_id is not None and project_id in self.projects)
@dataclass(frozen=True,slots=True)
class AuthenticatedUser:
    username:str
    role:Role
    projects:tuple[str,...]
    def can_access_project(self,project_id): return "*" in self.projects or (project_id is not None and project_id in self.projects)
class AuthManager:
    def __init__(self,users:Sequence[UserRecord],*,required=True):
        records=tuple(users)
        usernames=[user.username for user in records]
        if len(usernames)!=len(set(usernames)):
            raise AuthConfigurationError("configured usernames must be unique")
        self._users={user.username:user for user in records}
        self.required=required
    @classmethod
    def from_env(cls):
        required=os.getenv("NETREGRESS_AUTH_REQUIRED","0").lower() not in {"0","false","no"}; raw=os.getenv("NETREGRESS_AUTH_USERS_JSON","").strip()
        if not raw: return cls((),required=required)
        try: items=json.loads(raw)
        except json.JSONDecodeError as exc: raise AuthConfigurationError("NETREGRESS_AUTH_USERS_JSON is not valid JSON") from exc
        if not isinstance(items,list): raise AuthConfigurationError("NETREGRESS_AUTH_USERS_JSON must be an array")
        users=[]
        for index,item in enumerate(items):
            if not isinstance(item,dict):
                raise AuthConfigurationError(f"configured user at index {index} must be an object")
            username=item.get("username")
            password_hash=item.get("password_hash")
            if not isinstance(username,str) or not username.strip():
                raise AuthConfigurationError(f"configured user at index {index} has no valid username")
            if not isinstance(password_hash,str) or not password_hash.strip():
                raise AuthConfigurationError(f"configured user {username!r} has no password hash")
            try:
                role=Role(str(item.get("role","")).upper())
            except ValueError as exc:
                raise AuthConfigurationError(f"configured user {username!r} has an unsupported role") from exc
            projects=item.get("projects",["*"])
            if not isinstance(projects,list) or any(not isinstance(project,str) or not project.strip() for project in projects):
                raise AuthConfigurationError(f"projects for user {username!r} must be an array of non-empty strings")
            normalized_projects=tuple(project.strip() for project in projects)
            if "*" in normalized_projects and len(normalized_projects)!=1:
                raise AuthConfigurationError(f"wildcard project scope for user {username!r} cannot be combined with named projects")
            users.append(UserRecord(username.strip(),password_hash.strip(),role,normalized_projects))
        return cls(users,required=required)
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
