"""Add persistent identity, role permissions, sessions and audit records.

Revision ID: 20261113_06
Revises: 20261112_05
"""
from alembic import op
import sqlalchemy as sa

revision = "20261113_06"
down_revision = "20261112_05"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("workspace.read", "workspace", "read", "View the authenticated workspace"),
    ("workspace.manage", "workspace", "manage", "Manage workspace administration"),
    ("organizations.manage", "organizations", "manage", "Create and update organizations"),
    ("projects.read", "projects", "read", "View assigned projects"),
    ("projects.manage", "projects", "manage", "Create and update projects"),
    ("labs.read", "labs", "read", "View project Labs"),
    ("labs.manage", "labs", "manage", "Create and update project Labs"),
    ("members.manage", "members", "manage", "Assign and revoke project membership"),
    ("users.read", "users", "read", "View account directory"),
    ("users.manage", "users", "manage", "Invite and administer accounts"),
    ("roles.read", "roles", "read", "View role definitions"),
    ("roles.manage", "roles", "manage", "Create roles and assign permissions"),
    ("permissions.read", "permissions", "read", "View registered permissions"),
    ("permissions.manage", "permissions", "manage", "Manage permission registry"),
    ("runs.read", "runs", "read", "View project validation Runs"),
    ("runs.execute", "runs", "execute", "Launch and retry validation Runs"),
    ("evidence.read", "evidence", "read", "View Run evidence and artifacts"),
    ("quality.read", "quality", "read", "View quality, performance and regression data"),
    ("baselines.manage", "baselines", "manage", "Promote and manage baselines"),
    ("firmware.manage", "firmware", "manage", "Run authorized firmware operations"),
    ("audit.read", "audit", "read", "View administrative audit history"),
    ("system.manage", "system", "manage", "Manage protected system ownership"),
)
ROLE_PERMISSIONS = {
    "VIEWER": (
        "workspace.read", "projects.read", "labs.read", "runs.read",
        "evidence.read", "quality.read", "roles.read",
    ),
    "OPERATOR": (
        "workspace.read", "projects.read", "labs.read", "runs.read",
        "evidence.read", "quality.read", "roles.read", "runs.execute",
        "firmware.manage",
    ),
    "ADMIN": (
        "workspace.read", "workspace.manage", "projects.read", "projects.manage",
        "labs.read", "labs.manage", "members.manage", "users.read", "users.manage",
        "roles.read", "roles.manage", "permissions.read", "audit.read",
        "runs.read", "runs.execute", "evidence.read", "quality.read",
        "baselines.manage", "firmware.manage",
    ),
    "OWNER": tuple(item[0] for item in PERMISSIONS),
}


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("username", sa.String(collation="NOCASE"), primary_key=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="INVITED"),
        sa.Column("workspace_scope", sa.String(), nullable=False, server_default="MEMBERSHIP"),

        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("activated_at", sa.String(), nullable=True),
        sa.Column("password_changed_at", sa.String(), nullable=True),
        sa.CheckConstraint("status IN ('INVITED','ACTIVE','SUSPENDED','DEACTIVATED')", name="ck_users_status"),
        sa.CheckConstraint("workspace_scope IN ('MEMBERSHIP','WILDCARD')", name="ck_users_workspace_scope"),

    )
    op.create_index("uq_users_email", "users", ["email"], unique=True)
    op.create_index("idx_users_status", "users", ["status", "username"])
    op.create_table(
        "roles",
        sa.Column("role_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("scope_type", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint("scope_type IN ('GLOBAL','PROJECT')", name="ck_roles_scope"),
        sa.UniqueConstraint("name", "scope_type", name="uq_roles_name_scope"),
    )
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(), primary_key=True),
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.String(), sa.ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_code", sa.String(), sa.ForeignKey("permissions.code", ondelete="RESTRICT"), nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_code", name="pk_role_permissions"),
    )
    op.create_table(
        "role_assignments",
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("role_id", sa.String(), sa.ForeignKey("roles.role_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope_type", sa.String(), nullable=False),
        sa.Column("scope_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint("scope_type IN ('GLOBAL','PROJECT')", name="ck_role_assignments_scope"),
        sa.PrimaryKeyConstraint("username", "scope_type", "scope_id", name="pk_role_assignments"),
    )
    op.create_index("idx_role_assignments_role", "role_assignments", ["role_id"])
    op.create_index("idx_role_assignments_scope", "role_assignments", ["scope_type", "scope_id", "username"])
    op.create_table(
        "user_sessions",
        sa.Column("session_hash", sa.String(), primary_key=True),
        sa.Column("username", sa.String(), sa.ForeignKey("users.username", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("last_seen_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.String(), nullable=True),
    )
    op.create_index("idx_user_sessions_user", "user_sessions", ["username", "revoked_at", "expires_at"])
    op.create_table(
        "invitation_tokens",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("username", sa.String(), sa.ForeignKey("users.username", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("consumed_at", sa.String(), nullable=True),
    )
    op.create_index("idx_invitation_user", "invitation_tokens", ["username", "consumed_at"])
    op.create_table(
        "password_reset_tokens",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("username", sa.String(), sa.ForeignKey("users.username", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("consumed_at", sa.String(), nullable=True),
    )
    op.create_index("idx_password_reset_user", "password_reset_tokens", ["username", "consumed_at"])
    op.create_table(
        "audit_events",
        sa.Column("audit_id", sa.String(), primary_key=True),
        sa.Column("actor_username", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("details_json", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.String(), nullable=False),
    )
    op.create_index("idx_audit_events_time", "audit_events", ["occurred_at", "audit_id"])
    op.create_index("idx_audit_events_resource", "audit_events", ["resource_type", "resource_id", "occurred_at"])

    op.execute(
        """CREATE TRIGGER trg_audit_events_no_update
           BEFORE UPDATE ON audit_events
           BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_audit_events_no_delete
           BEFORE DELETE ON audit_events
           BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END"""
    )

    bind = op.get_bind()
    now = "2026-11-13T00:00:00+00:00"
    for code, resource, action, description in PERMISSIONS:
        bind.execute(
            sa.text("INSERT INTO permissions(code,resource,action,description) VALUES(:code,:resource,:action,:description)"),
            {"code": code, "resource": resource, "action": action, "description": description},
        )
    for scope in ("GLOBAL", "PROJECT"):
        for role_name in ("OWNER", "ADMIN", "OPERATOR", "VIEWER"):
            role_id = f"{scope.lower()}_{role_name.lower()}"
            bind.execute(
                sa.text(
                    """INSERT INTO roles(
                        role_id,name,scope_type,description,is_system,created_at,updated_at,created_by
                    ) VALUES(:role_id,:name,:scope,:description,1,:now,:now,'system')"""
                ),
                {
                    "role_id": role_id, "name": role_name, "scope": scope,
                    "description": f"Built-in {scope.lower()} {role_name.lower()} role",
                    "now": now,
                },
            )
            for permission in ROLE_PERMISSIONS[role_name]:
                bind.execute(
                    sa.text("INSERT INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                    {"role": role_id, "permission": permission},
                )
    bind.exec_driver_sql(
        """
        INSERT INTO role_assignments(username,role_id,scope_type,scope_id,created_at,created_by)
        SELECT username, 'project_' || lower(role), 'PROJECT', project_id, created_at, created_by
        FROM project_memberships
        """
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES ('version','15') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES ('alembic_revision','20261113_06') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Persistent identity and authorization are not destructively reversible. "
        "Restore a verified pre-migration SQLite backup instead."
    )
