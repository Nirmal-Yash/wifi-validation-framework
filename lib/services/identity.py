"""Persistent local identity, RBAC, account lifecycle and audit store.

The database is authoritative for active accounts, role assignments and session
revocation. Environment-configured users are accepted only as a bootstrap path.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from lib.repositories import SQLiteDatabase


class IdentityError(RuntimeError):
    """Base identity service error."""


class IdentityConflictError(IdentityError):
    """An identity or role conflicts with existing state."""


class IdentityNotFoundError(IdentityError):
    """An identity or token does not exist."""


class IdentityPolicyError(IdentityError):
    """An identity transition violates a security invariant."""


class IdentityStore:
    ACTION_PERMISSION = {
        "view": "workspace.read",
        "execute": "runs.execute",
        "admin": "workspace.manage",
        "owner": "system.manage",
    }
    USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def iso(value: datetime | None = None) -> str:
        return (value or IdentityStore.now()).astimezone(timezone.utc).isoformat()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def validate_password(password: str) -> None:
        if not isinstance(password, str) or len(password) < 12:
            raise ValueError("password must contain at least 12 characters")
        if len(password) > 1024:
            raise ValueError("password is too long")

    @staticmethod
    def _role_id(name: str, scope_type: str) -> str:
        return f"{scope_type.lower()}_{name.lower()}"

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)
            ).fetchone()
        return self._row(row)

    def list_users(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT u.username,u.email,u.display_name,u.status,u.created_at,
                          u.updated_at,u.created_by,u.activated_at,u.password_changed_at,
                          r.role_id AS global_role_id,r.name AS global_role
                   FROM users u
                   LEFT JOIN role_assignments a
                     ON a.username=u.username AND a.scope_type='GLOBAL' AND a.scope_id='*'
                   LEFT JOIN roles r ON r.role_id=a.role_id
                   ORDER BY u.username COLLATE NOCASE"""
            ).fetchall()
        return [dict(row) for row in rows]

    def ensure_bootstrap_user(
        self, username: str, password_hash: str, role_name: str, *,
        actor: str = "bootstrap", workspace_scope: str = "MEMBERSHIP",
    ) -> dict[str, Any]:
        username = username.strip()
        role_name = role_name.upper()
        workspace_scope = workspace_scope.upper()
        if workspace_scope not in {"MEMBERSHIP","WILDCARD"}:
            raise ValueError("workspace scope must be MEMBERSHIP or WILDCARD")
        if not self.USERNAME_PATTERN.fullmatch(username):
            raise ValueError("configured username does not satisfy the account identifier policy")
        if role_name not in {"OWNER", "ADMIN", "OPERATOR", "VIEWER"}:
            raise ValueError("unsupported bootstrap role")
        now = self.iso()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)
            ).fetchone()
            if row is None:
                connection.execute(
                    """INSERT INTO users(
                        username,email,display_name,password_hash,status,workspace_scope,
                        created_at,updated_at,created_by,activated_at,password_changed_at
                    ) VALUES(?,NULL,?,?, 'ACTIVE',?,?,?,?,?,?)""",
                    (username, username, password_hash, workspace_scope, now, now, actor, now, now),
                )
                connection.execute(
                    """INSERT INTO role_assignments(
                        username,role_id,scope_type,scope_id,created_at,created_by
                    ) VALUES(?,?,'GLOBAL','*',?,?)""",
                    (username, self._role_id(role_name, "GLOBAL"), now, actor),
                )
                self._audit_in_transaction(
                    connection, actor, "ACCOUNT_BOOTSTRAPPED", "USER", username,
                    {"global_role": role_name},
                )
            elif row["status"] != "ACTIVE":
                raise IdentityPolicyError("this account is not active; configured credentials cannot reactivate it")
            else:
                assignment = connection.execute(
                    """SELECT role_id FROM role_assignments
                       WHERE username=? AND scope_type='GLOBAL' AND scope_id='*'""",
                    (username,),
                ).fetchone()
                if assignment is None:
                    connection.execute(
                        """INSERT INTO role_assignments(
                            username,role_id,scope_type,scope_id,created_at,created_by
                        ) VALUES(?,?,'GLOBAL','*',?,?)""",
                        (username, self._role_id(role_name, "GLOBAL"), now, actor),
                    )
        user = self.get_user(username)
        assert user is not None
        return user

    def create_session(self, username: str, lifetime_seconds: int = 1800) -> str:
        if lifetime_seconds < 60 or lifetime_seconds > 86400:
            raise ValueError("session lifetime must be between 60 and 86400 seconds")
        token = secrets.token_urlsafe(32)
        now = self.now()
        with self.database.transaction(immediate=True) as connection:
            user = connection.execute(
                "SELECT status FROM users WHERE username=?", (username,)
            ).fetchone()
            if user is None or user["status"] != "ACTIVE":
                raise IdentityPolicyError("only active accounts can create sessions")
            connection.execute(
                """INSERT INTO user_sessions(
                    session_hash,username,created_at,last_seen_at,expires_at,revoked_at
                ) VALUES(?,?,?,?,?,NULL)""",
                (
                    self._token_hash(token), username, self.iso(now), self.iso(now),
                    self.iso(now + timedelta(seconds=lifetime_seconds)),
                ),
            )
        return token

    def validate_session(
        self, username: str, token: str, *,
        touch: bool = False, idle_timeout_seconds: int = 1800,
    ) -> bool:
        if not token:
            return False
        now = self.iso()
        with self.database.transaction(immediate=touch) as connection:
            row = connection.execute(
                """SELECT s.revoked_at,s.expires_at,u.status
                   FROM user_sessions s JOIN users u ON u.username=s.username
                   WHERE s.session_hash=? AND s.username=?""",
                (self._token_hash(token), username),
            ).fetchone()
            if row is None or row["revoked_at"] is not None:
                return False
            if row["status"] != "ACTIVE" or row["expires_at"] <= now:
                return False
            if touch:
                expires_at=self.iso(self.now()+timedelta(seconds=max(60,min(86400,int(idle_timeout_seconds)))))
                connection.execute(
                    "UPDATE user_sessions SET last_seen_at=?,expires_at=? WHERE session_hash=?",
                    (now,expires_at,self._token_hash(token)),
                )
        return True

    def revoke_current_session(self, username: str, token: str) -> bool:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE user_sessions SET revoked_at=?
                   WHERE username=? AND session_hash=? AND revoked_at IS NULL""",
                (self.iso(), username, self._token_hash(token)),
            )
        return cursor.rowcount == 1

    def revoke_sessions(self, username: str) -> int:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE user_sessions SET revoked_at=?
                   WHERE username=? AND revoked_at IS NULL""",
                (self.iso(), username),
            )
        return int(cursor.rowcount)

    def list_sessions(self, username: str) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT created_at,last_seen_at,expires_at,revoked_at
                   FROM user_sessions WHERE username=?
                   ORDER BY created_at DESC""",
                (username,),
            ).fetchall()
        return [dict(row) for row in rows]

    def invite_user(
        self, *, username: str, email: str | None, display_name: str,
        global_role_id: str, actor: str, lifetime_hours: int = 24,
    ) -> tuple[dict[str, Any], str]:
        username = username.strip()
        display_name = display_name.strip()
        email = email.strip().lower() if isinstance(email, str) and email.strip() else None
        if not self.USERNAME_PATTERN.fullmatch(username):
            raise ValueError("username must be 2–64 characters and use letters, numbers, dot, underscore or hyphen")
        if not display_name or len(display_name) > 120:
            raise ValueError("display name must contain 1–120 characters")
        if email and (len(email) > 254 or "@" not in email):
            raise ValueError("email address is invalid")
        if lifetime_hours < 1 or lifetime_hours > 168:
            raise ValueError("invitation lifetime must be between 1 and 168 hours")
        token = secrets.token_urlsafe(32)
        now = self.now()
        with self.database.transaction(immediate=True) as connection:
            role = connection.execute(
                "SELECT scope_type FROM roles WHERE role_id=?", (global_role_id,)
            ).fetchone()
            if role is None or role["scope_type"] != "GLOBAL":
                raise ValueError("a valid Global role is required")
            try:
                connection.execute(
                    """INSERT INTO users(
                        username,email,display_name,password_hash,status,created_at,
                        updated_at,created_by,activated_at,password_changed_at
                    ) VALUES(?,?,?,NULL,'INVITED',?,?,?,NULL,NULL)""",
                    (username,email,display_name,self.iso(now),self.iso(now),actor),
                )
                connection.execute(
                    """INSERT INTO role_assignments(
                        username,role_id,scope_type,scope_id,created_at,created_by
                    ) VALUES(?,?,'GLOBAL','*',?,?)""",
                    (username,global_role_id,self.iso(now),actor),
                )
                connection.execute(
                    """INSERT INTO invitation_tokens(
                        token_hash,username,created_at,expires_at,created_by,consumed_at
                    ) VALUES(?,?,?,?,?,NULL)""",
                    (
                        self._token_hash(token),username,self.iso(now),
                        self.iso(now + timedelta(hours=lifetime_hours)),actor,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise IdentityConflictError("username or email already exists") from exc
            self._audit_in_transaction(
                connection,actor,"USER_INVITED","USER",username,
                {"email":email,"global_role_id":global_role_id},
            )
        user = self.get_user(username)
        assert user is not None
        return user, token

    def accept_invitation(self, token: str, password: str) -> dict[str, Any]:
        self.validate_password(password)
        now = self.iso()
        password_hash = generate_password_hash(password, method="scrypt")
        with self.database.transaction(immediate=True) as connection:
            invite = connection.execute(
                """SELECT i.username,i.expires_at,i.consumed_at,u.status
                   FROM invitation_tokens i JOIN users u ON u.username=i.username
                   WHERE i.token_hash=?""",
                (self._token_hash(token),),
            ).fetchone()
            if (
                invite is None or invite["consumed_at"] is not None
                or invite["expires_at"] <= now or invite["status"] != "INVITED"
            ):
                raise IdentityPolicyError("invitation token is invalid, expired or already used")
            username = invite["username"]
            connection.execute(
                """UPDATE users SET password_hash=?,status='ACTIVE',
                   activated_at=?,password_changed_at=?,updated_at=? WHERE username=?""",
                (password_hash,now,now,now,username),
            )
            connection.execute(
                "UPDATE invitation_tokens SET consumed_at=? WHERE token_hash=?",
                (now,self._token_hash(token)),
            )
            self._audit_in_transaction(
                connection,username,"INVITATION_ACCEPTED","USER",username,{},
            )
        user = self.get_user(username)
        assert user is not None
        return user

    def issue_password_reset(self, username: str, actor: str, lifetime_minutes: int = 30) -> str:
        if lifetime_minutes < 5 or lifetime_minutes > 120:
            raise ValueError("password reset lifetime must be between 5 and 120 minutes")
        token = secrets.token_urlsafe(32)
        now = self.now()
        with self.database.transaction(immediate=True) as connection:
            user = connection.execute(
                "SELECT status FROM users WHERE username=?", (username,)
            ).fetchone()
            if user is None:
                raise IdentityNotFoundError("account not found")
            if user["status"] != "ACTIVE":
                raise IdentityPolicyError("password reset is available only for active accounts")
            connection.execute(
                """INSERT INTO password_reset_tokens(
                    token_hash,username,created_at,expires_at,created_by,consumed_at
                ) VALUES(?,?,?,?,?,NULL)""",
                (
                    self._token_hash(token),username,self.iso(now),
                    self.iso(now + timedelta(minutes=lifetime_minutes)),actor,
                ),
            )
            self._audit_in_transaction(
                connection,actor,"PASSWORD_RESET_ISSUED","USER",username,{},
            )
        return token

    def complete_password_reset(self, token: str, password: str) -> dict[str, Any]:
        self.validate_password(password)
        now = self.iso()
        password_hash = generate_password_hash(password, method="scrypt")
        with self.database.transaction(immediate=True) as connection:
            record = connection.execute(
                """SELECT username,expires_at,consumed_at FROM password_reset_tokens
                   WHERE token_hash=?""",
                (self._token_hash(token),),
            ).fetchone()
            if record is None or record["consumed_at"] is not None or record["expires_at"] <= now:
                raise IdentityPolicyError("password reset token is invalid, expired or already used")
            username = record["username"]
            connection.execute(
                """UPDATE users SET password_hash=?,password_changed_at=?,updated_at=?
                   WHERE username=? AND status='ACTIVE'""",
                (password_hash,now,now,username),
            )
            connection.execute(
                "UPDATE password_reset_tokens SET consumed_at=? WHERE token_hash=?",
                (now,self._token_hash(token)),
            )
            connection.execute(
                "UPDATE user_sessions SET revoked_at=? WHERE username=? AND revoked_at IS NULL",
                (now,username),
            )
            self._audit_in_transaction(
                connection,username,"PASSWORD_RESET_COMPLETED","USER",username,{},
            )
        user = self.get_user(username)
        assert user is not None
        return user

    def set_user_status(self, username: str, status: str, actor: str) -> dict[str, Any]:
        status = status.upper()
        if status not in {"ACTIVE","SUSPENDED","DEACTIVATED"}:
            raise ValueError("unsupported account status")
        now = self.iso()
        with self.database.transaction(immediate=True) as connection:
            user = connection.execute(
                "SELECT status FROM users WHERE username=?", (username,)
            ).fetchone()
            if user is None:
                raise IdentityNotFoundError("account not found")
            if user["status"] == "DEACTIVATED" and status != "DEACTIVATED":
                raise IdentityPolicyError("deactivated accounts cannot be reactivated")
            if status in {"SUSPENDED","DEACTIVATED"} and self._is_last_active_owner(connection,username):
                raise IdentityPolicyError("the last active Global Owner cannot be suspended or deactivated")
            connection.execute(
                "UPDATE users SET status=?,updated_at=? WHERE username=?",
                (status,now,username),
            )
            if status in {"SUSPENDED","DEACTIVATED"}:
                connection.execute(
                    "UPDATE user_sessions SET revoked_at=? WHERE username=? AND revoked_at IS NULL",
                    (now,username),
                )
            self._audit_in_transaction(
                connection,actor,"ACCOUNT_"+status,"USER",username,{},
            )
        result = self.get_user(username)
        assert result is not None
        return result

    def _is_last_active_owner(self, connection: sqlite3.Connection, username: str) -> bool:
        target = connection.execute(
            """SELECT 1 FROM role_assignments a
               JOIN roles r ON r.role_id=a.role_id
               JOIN users u ON u.username=a.username
               WHERE a.username=? AND a.scope_type='GLOBAL' AND a.scope_id='*'
                 AND r.name='OWNER' AND u.status='ACTIVE'""",
            (username,),
        ).fetchone()
        if target is None:
            return False
        count = connection.execute(
            """SELECT COUNT(*) FROM role_assignments a
               JOIN roles r ON r.role_id=a.role_id
               JOIN users u ON u.username=a.username
               WHERE a.scope_type='GLOBAL' AND a.scope_id='*'
                 AND r.name='OWNER' AND u.status='ACTIVE'""",
        ).fetchone()[0]
        return int(count) <= 1

    def assign_role(
        self, *, username: str, role_id: str, scope_type: str,
        scope_id: str, actor: str,
    ) -> None:
        scope_type = scope_type.upper()
        if scope_type not in {"GLOBAL","PROJECT"}:
            raise ValueError("scope_type must be GLOBAL or PROJECT")
        if (scope_type == "GLOBAL" and scope_id != "*") or (scope_type == "PROJECT" and not scope_id):
            raise ValueError("invalid role assignment scope")
        now = self.iso()
        with self.database.transaction(immediate=True) as connection:
            role = connection.execute(
                "SELECT scope_type,name FROM roles WHERE role_id=?", (role_id,)
            ).fetchone()
            if role is None or role["scope_type"] != scope_type:
                raise ValueError("role does not exist in the requested scope")
            user = connection.execute(
                "SELECT status FROM users WHERE username=?", (username,)
            ).fetchone()
            if user is None:
                raise IdentityNotFoundError("account not found")
            if scope_type == "GLOBAL":
                current = connection.execute(
                    """SELECT r.name FROM role_assignments a JOIN roles r ON r.role_id=a.role_id
                       WHERE a.username=? AND a.scope_type='GLOBAL' AND a.scope_id='*'""",
                    (username,),
                ).fetchone()
                if current and current["name"] == "OWNER" and role["name"] != "OWNER":
                    if self._is_last_active_owner(connection,username):
                        raise IdentityPolicyError("the last active Global Owner cannot be demoted")
            connection.execute(
                """INSERT INTO role_assignments(username,role_id,scope_type,scope_id,created_at,created_by)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(username,scope_type,scope_id) DO UPDATE SET
                     role_id=excluded.role_id,created_at=excluded.created_at,created_by=excluded.created_by""",
                (username,role_id,scope_type,scope_id,now,actor),
            )
            self._audit_in_transaction(
                connection,actor,"ROLE_ASSIGNED","USER",username,
                {"role_id":role_id,"scope_type":scope_type,"scope_id":scope_id},
            )

    def create_role(self, *, name: str, scope_type: str, description: str, actor: str) -> dict[str, Any]:
        name = name.strip()
        scope_type = scope_type.upper()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _.-]{1,47}",name):
            raise ValueError("role name must be 2–48 characters and begin with a letter")
        if scope_type not in {"GLOBAL","PROJECT"}:
            raise ValueError("role scope must be GLOBAL or PROJECT")
        role_id = "role_" + secrets.token_hex(12)
        now = self.iso()
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO roles(
                        role_id,name,scope_type,description,is_system,created_at,updated_at,created_by
                    ) VALUES(?,?,?,?,0,?,?,?)""",
                    (role_id,name,scope_type,description.strip(),now,now,actor),
                )
                self._audit_in_transaction(
                    connection,actor,"ROLE_CREATED","ROLE",role_id,
                    {"name":name,"scope_type":scope_type},
                )
        except sqlite3.IntegrityError as exc:
            raise IdentityConflictError("a role with this name already exists in the selected scope") from exc
        return self.get_role(role_id)

    def get_role(self, role_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            role = connection.execute("SELECT * FROM roles WHERE role_id=?", (role_id,)).fetchone()
            if role is None:
                return None
            result = dict(role)
            result["permissions"] = [
                row["permission_code"] for row in connection.execute(
                    "SELECT permission_code FROM role_permissions WHERE role_id=? ORDER BY permission_code",
                    (role_id,),
                ).fetchall()
            ]
        return result

    def list_roles(self, scope_type: str | None = None) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            if scope_type:
                roles = connection.execute(
                    "SELECT * FROM roles WHERE scope_type=? ORDER BY is_system DESC,name COLLATE NOCASE",
                    (scope_type.upper(),),
                ).fetchall()
            else:
                roles = connection.execute(
                    "SELECT * FROM roles ORDER BY scope_type,is_system DESC,name COLLATE NOCASE"
                ).fetchall()
            result = []
            for row in roles:
                item = dict(row)
                item["permissions"] = [
                    permission["permission_code"] for permission in connection.execute(
                        "SELECT permission_code FROM role_permissions WHERE role_id=? ORDER BY permission_code",
                        (item["role_id"],),
                    ).fetchall()
                ]
                result.append(item)
        return result

    def list_permissions(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            return [
                dict(row) for row in connection.execute(
                    "SELECT code,resource,action,description FROM permissions ORDER BY resource,action,code"
                ).fetchall()
            ]

    def set_role_permissions(self, role_id: str, permission_codes: list[str], actor: str) -> dict[str, Any]:
        if not isinstance(permission_codes,list) or any(not isinstance(code,str) for code in permission_codes):
            raise ValueError("permissions must be an array of permission codes")
        codes = list(dict.fromkeys(permission_codes))
        now = self.iso()
        with self.database.transaction(immediate=True) as connection:
            role = connection.execute("SELECT * FROM roles WHERE role_id=?", (role_id,)).fetchone()
            if role is None:
                raise IdentityNotFoundError("role not found")
            if role["is_system"]:
                raise IdentityPolicyError("built-in roles are immutable; create a custom role instead")
            if role["scope_type"] == "GLOBAL" and "system.manage" in codes:
                raise IdentityPolicyError("custom Global roles cannot grant protected system ownership")
            unknown = [
                code for code in codes
                if connection.execute("SELECT 1 FROM permissions WHERE code=?", (code,)).fetchone() is None
            ]
            if unknown:
                raise ValueError("unknown permission code(s): " + ", ".join(unknown))
            connection.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
            connection.executemany(
                "INSERT INTO role_permissions(role_id,permission_code) VALUES(?,?)",
                [(role_id,code) for code in codes],
            )
            connection.execute("UPDATE roles SET updated_at=? WHERE role_id=?", (now,role_id))
            self._audit_in_transaction(
                connection,actor,"ROLE_PERMISSIONS_UPDATED","ROLE",role_id,
                {"permission_codes":codes},
            )
        result = self.get_role(role_id)
        assert result is not None
        return result

    def delete_role(self, role_id: str, actor: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            role = connection.execute("SELECT * FROM roles WHERE role_id=?", (role_id,)).fetchone()
            if role is None:
                raise IdentityNotFoundError("role not found")
            if role["is_system"]:
                raise IdentityPolicyError("built-in roles cannot be deleted")
            assigned = connection.execute(
                "SELECT 1 FROM role_assignments WHERE role_id=? LIMIT 1", (role_id,)
            ).fetchone()
            if assigned:
                raise IdentityPolicyError("remove all assignments before deleting this role")
            connection.execute("DELETE FROM roles WHERE role_id=?", (role_id,))
            self._audit_in_transaction(
                connection,actor,"ROLE_DELETED","ROLE",role_id,
                {"name":role["name"],"scope_type":role["scope_type"]},
            )

    def project_ids_for_user(self, username: str) -> tuple[str, ...]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT scope_id FROM role_assignments
                   WHERE username=? AND scope_type='PROJECT'
                   UNION
                   SELECT project_id FROM project_memberships WHERE username=?""",
                (username,username),
            ).fetchall()
        return tuple(sorted({row[0] for row in rows}))

    def permission_codes(self, username: str, project_id: str | None = None) -> tuple[str, ...]:
        with self.database.connection() as connection:
            global_role = connection.execute(
                """SELECT role_id FROM role_assignments
                   WHERE username=? AND scope_type='GLOBAL' AND scope_id='*'""",
                (username,),
            ).fetchone()
            if global_role is None:
                return ()
            global_codes = {
                row[0] for row in connection.execute(
                    "SELECT permission_code FROM role_permissions WHERE role_id=?",
                    (global_role["role_id"],),
                ).fetchall()
            }
            if project_id is None:
                return tuple(sorted(global_codes))
            project_role = connection.execute(
                """SELECT role_id FROM role_assignments
                   WHERE username=? AND scope_type='PROJECT' AND scope_id=?""",
                (username,project_id),
            ).fetchone()
            if project_role is None:
                membership = connection.execute(
                    """SELECT role FROM project_memberships
                       WHERE username=? AND project_id=?""",
                    (username,project_id),
                ).fetchone()
                if membership is None:
                    return ()
                project_role_id = self._role_id(membership["role"],"PROJECT")
            else:
                project_role_id = project_role["role_id"]
            project_codes = {
                row[0] for row in connection.execute(
                    "SELECT permission_code FROM role_permissions WHERE role_id=?",
                    (project_role_id,),
                ).fetchall()
            }
        # Project authority is intentionally intersected with Global authority.
        return tuple(sorted(global_codes & project_codes))

    def authorize(self, username: str, action: str, project_id: str | None = None, *, wildcard: bool = False) -> bool:
        permission = self.ACTION_PERMISSION.get(action)
        if permission is None:
            return False
        user = self.get_user(username)
        if user is None or user["status"] != "ACTIVE":
            return False
        global_permissions = set(self.permission_codes(username))
        if permission not in global_permissions:
            return False
        if project_id is None or wildcard:
            return True
        if project_id == "__cross_project__":
            return False
        return permission in set(self.permission_codes(username,project_id))

    def assign_project_role(self, username: str, project_id: str, role_id: str, actor: str) -> None:
        role = self.get_role(role_id)
        if role is None or role["scope_type"] != "PROJECT":
            raise ValueError("role does not exist in Project scope")
        now = self.iso()
        base_role = role["name"] if role["name"] in {"OWNER", "ADMIN", "OPERATOR", "VIEWER"} else "VIEWER"
        with self.database.transaction(immediate=True) as connection:
            membership = connection.execute(
                "SELECT role FROM project_memberships WHERE username=? AND project_id=?",
                (username, project_id),
            ).fetchone()
            if membership is None:
                raise IdentityNotFoundError("Project membership not found")
            if membership["role"] == "OWNER" and role["name"] != "OWNER":
                owners = connection.execute(
                    "SELECT COUNT(*) FROM project_memberships WHERE project_id=? AND role='OWNER'",
                    (project_id,),
                ).fetchone()[0]
                if int(owners) <= 1:
                    raise IdentityPolicyError("the last Project Owner cannot be demoted")
            connection.execute(
                """UPDATE project_memberships SET role=?,created_at=?,created_by=?
                   WHERE username=? AND project_id=?""",
                (base_role, now, actor, username, project_id),
            )
            connection.execute(
                """INSERT INTO role_assignments(
                    username,role_id,scope_type,scope_id,created_at,created_by
                ) VALUES(?,?,'PROJECT',?,?,?)
                ON CONFLICT(username,scope_type,scope_id) DO UPDATE SET
                    role_id=excluded.role_id,created_at=excluded.created_at,
                    created_by=excluded.created_by""",
                (username, role_id, project_id, now, actor),
            )
            self._audit_in_transaction(
                connection, actor, "PROJECT_MEMBER_ROLE_CHANGED", "PROJECT",
                project_id, {"username": username, "role_id": role_id},
            )

    def demote_project_owner(
        self, *, username: str, project_id: str, new_role_id: str, actor: str,
    ) -> None:
        self.assign_project_role(username, project_id, new_role_id, actor)

    def _audit_in_transaction(
        self, connection: sqlite3.Connection, actor: str, action: str,
        resource_type: str, resource_id: str, details: dict[str, Any],
    ) -> None:
        connection.execute(
            """INSERT INTO audit_events(
                audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "AUD-" + secrets.token_hex(12),actor,action,resource_type,resource_id,
                json.dumps(details,sort_keys=True,separators=(",",":")),self.iso(),
            ),
        )

    def record_audit(
        self, actor: str, action: str, resource_type: str,
        resource_id: str, details: dict[str, Any] | None = None,
    ) -> None:
        with self.database.transaction(immediate=True) as connection:
            self._audit_in_transaction(
                connection,actor,action,resource_type,resource_id,details or {},
            )

    def list_audit(self, *, limit: int = 100, resource_type: str | None = None) -> list[dict[str, Any]]:
        limit = min(500,max(1,int(limit)))
        with self.database.connection() as connection:
            if resource_type:
                rows = connection.execute(
                    """SELECT * FROM audit_events WHERE resource_type=?
                       ORDER BY occurred_at DESC,audit_id DESC LIMIT ?""",
                    (resource_type,limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM audit_events ORDER BY occurred_at DESC,audit_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        results=[]
        for row in rows:
            item=dict(row)
            try:
                item["details"]=json.loads(item.pop("details_json"))
            except (TypeError,ValueError):
                item["details"]={}
            results.append(item)
        return results
