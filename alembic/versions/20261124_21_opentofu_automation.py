"""Add isolated, approval-gated OpenTofu workspace and plan lifecycle.

Revision ID: 20261124_21
Revises: 20261124_20
"""
from alembic import op
import sqlalchemy as sa

revision = "20261124_21"
down_revision = "20261124_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opentofu_workspaces",
        sa.Column("workspace_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("module_sha256", sa.String(64), nullable=False),
        sa.Column("variables_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="ck_opentofu_workspaces_name"),
        sa.CheckConstraint("module_key GLOB '[a-z0-9]*' AND length(module_key) BETWEEN 1 AND 64", name="ck_opentofu_workspaces_module"),
        sa.CheckConstraint("length(module_sha256)=64 AND module_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_opentofu_workspaces_module_hash"),
        sa.CheckConstraint("length(variables_json) BETWEEN 2 AND 65536", name="ck_opentofu_workspaces_variables_size"),
        sa.CheckConstraint("status IN ('ACTIVE','RECOVERY_REQUIRED','DESTROYED')", name="ck_opentofu_workspaces_status"),
        sa.UniqueConstraint("project_id", "lab_id", "name", name="uq_opentofu_workspace_lab_name"),
        sa.UniqueConstraint("workspace_id", "project_id", "lab_id", name="uq_opentofu_workspace_scope"),
    )
    op.create_index("idx_opentofu_workspaces_project_created", "opentofu_workspaces", ["project_id", "created_at"])
    op.create_index("idx_opentofu_workspaces_lab", "opentofu_workspaces", ["lab_id", "status"])

    op.create_table(
        "opentofu_plans",
        sa.Column("plan_id", sa.String(32), primary_key=True),
        sa.Column("workspace_id", sa.String(32), sa.ForeignKey("opentofu_workspaces.workspace_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("plan_file", sa.String(128), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("approved_at", sa.String(), nullable=True),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id", "project_id", "lab_id"], ["opentofu_workspaces.workspace_id", "opentofu_workspaces.project_id", "opentofu_workspaces.lab_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("kind IN ('APPLY','DESTROY','RECOVERY')", name="ck_opentofu_plans_kind"),
        sa.CheckConstraint("length(plan_sha256)=64 AND plan_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_opentofu_plans_hash"),
        sa.CheckConstraint("plan_file GLOB '.netregress/plans/*.tfplan'", name="ck_opentofu_plans_file"),
        sa.CheckConstraint("length(summary_json) BETWEEN 2 AND 4194304", name="ck_opentofu_plans_summary_size"),
        sa.CheckConstraint("status IN ('PREVIEWED','APPROVED','APPLYING','APPLIED','FAILED')", name="ck_opentofu_plans_status"),
        sa.CheckConstraint("(status IN ('APPROVED','APPLYING','APPLIED','FAILED') AND approved_at IS NOT NULL AND approved_by IS NOT NULL) OR (status='PREVIEWED' AND approved_at IS NULL AND approved_by IS NULL)", name="ck_opentofu_plans_approval"),
    )
    op.create_index("idx_opentofu_plans_project_created", "opentofu_plans", ["project_id", "created_at"])
    op.create_index("idx_opentofu_plans_workspace", "opentofu_plans", ["workspace_id", "created_at"])

    op.create_table(
        "opentofu_approvals",
        sa.Column("approval_id", sa.String(32), primary_key=True),
        sa.Column("plan_id", sa.String(32), sa.ForeignKey("opentofu_plans.plan_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column("confirmed_at", sa.String(), nullable=False),
        sa.CheckConstraint("length(plan_sha256)=64 AND plan_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_opentofu_approvals_hash"),
        sa.UniqueConstraint("plan_id", "plan_sha256", name="uq_opentofu_approval_plan_hash"),
    )
    op.create_index("idx_opentofu_approvals_plan", "opentofu_approvals", ["plan_id", "confirmed_at"])

    op.create_table(
        "opentofu_executions",
        sa.Column("execution_id", sa.String(32), primary_key=True),
        sa.Column("plan_id", sa.String(32), sa.ForeignKey("opentofu_plans.plan_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("executed_by", sa.String(128), nullable=False),
        sa.CheckConstraint("length(plan_sha256)=64 AND plan_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_opentofu_executions_hash"),
        sa.CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED')", name="ck_opentofu_executions_status"),
        sa.CheckConstraint("length(result_json) BETWEEN 2 AND 32768", name="ck_opentofu_executions_result_size"),
        sa.CheckConstraint("(status='RUNNING' AND completed_at IS NULL) OR (status IN ('SUCCEEDED','FAILED') AND completed_at IS NOT NULL)", name="ck_opentofu_executions_completion"),
    )
    op.create_index("idx_opentofu_executions_plan", "opentofu_executions", ["plan_id", "started_at"])

    op.execute("""CREATE TRIGGER trg_opentofu_workspace_scope_insert
        BEFORE INSERT ON opentofu_workspaces
        WHEN NOT EXISTS (
            SELECT 1 FROM labs l JOIN projects p ON p.project_id=l.project_id
            WHERE l.lab_id=NEW.lab_id AND l.project_id=NEW.project_id
              AND l.status='ACTIVE' AND p.status='ACTIVE'
        )
        BEGIN SELECT RAISE(ABORT, 'OpenTofu workspace requires an active Lab in the selected Project'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_workspace_identity_immutable
        BEFORE UPDATE OF workspace_id,project_id,lab_id,name,module_key,module_sha256,variables_json,created_at,created_by
        ON opentofu_workspaces
        BEGIN SELECT RAISE(ABORT, 'OpenTofu workspace identity and module snapshot are immutable'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_workspace_state_transition
        BEFORE UPDATE OF status ON opentofu_workspaces
        WHEN NOT (
            OLD.status=NEW.status
            OR (OLD.status='ACTIVE' AND NEW.status IN ('RECOVERY_REQUIRED','DESTROYED'))
            OR (OLD.status='RECOVERY_REQUIRED' AND NEW.status IN ('ACTIVE','DESTROYED'))
        )
        BEGIN SELECT RAISE(ABORT, 'OpenTofu workspace state transition is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_workspace_no_delete
        BEFORE DELETE ON opentofu_workspaces
        BEGIN SELECT RAISE(ABORT, 'OpenTofu workspace history and state cannot be deleted'); END""")

    op.execute("""CREATE TRIGGER trg_opentofu_plan_scope_insert
        BEFORE INSERT ON opentofu_plans
        WHEN NOT EXISTS (
            SELECT 1 FROM opentofu_workspaces w
            WHERE w.workspace_id=NEW.workspace_id
              AND w.project_id=NEW.project_id AND w.lab_id=NEW.lab_id
              AND w.status IN ('ACTIVE','RECOVERY_REQUIRED')
        )
        BEGIN SELECT RAISE(ABORT, 'OpenTofu plan scope does not match an active workspace'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_plan_identity_immutable
        BEFORE UPDATE OF plan_id,workspace_id,project_id,lab_id,kind,plan_sha256,plan_file,summary_json,created_at,created_by
        ON opentofu_plans
        BEGIN SELECT RAISE(ABORT, 'OpenTofu plan content is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_plan_state_transition
        BEFORE UPDATE OF status ON opentofu_plans
        WHEN NOT (
            OLD.status=NEW.status
            OR (OLD.status='PREVIEWED' AND NEW.status='APPROVED')
            OR (OLD.status='APPROVED' AND NEW.status='APPLYING')
            OR (OLD.status='APPLYING' AND NEW.status IN ('APPLIED','FAILED'))
        )
        BEGIN SELECT RAISE(ABORT, 'OpenTofu plan state transition is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_plan_approval_immutable
        BEFORE UPDATE OF approved_at,approved_by ON opentofu_plans
        WHEN OLD.status <> 'PREVIEWED'
        BEGIN SELECT RAISE(ABORT, 'OpenTofu plan approval identity is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_plan_no_delete
        BEFORE DELETE ON opentofu_plans
        BEGIN SELECT RAISE(ABORT, 'OpenTofu plan history cannot be deleted'); END""")

    op.execute("""CREATE TRIGGER trg_opentofu_approval_scope_insert
        BEFORE INSERT ON opentofu_approvals
        WHEN NOT EXISTS (
            SELECT 1 FROM opentofu_plans p
            WHERE p.plan_id=NEW.plan_id AND p.plan_sha256=NEW.plan_sha256 AND p.status='PREVIEWED'
        )
        BEGIN SELECT RAISE(ABORT, 'OpenTofu approval must match a PREVIEWED plan hash'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_approvals_immutable
        BEFORE UPDATE ON opentofu_approvals
        BEGIN SELECT RAISE(ABORT, 'OpenTofu approval evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_approvals_no_delete
        BEFORE DELETE ON opentofu_approvals
        BEGIN SELECT RAISE(ABORT, 'OpenTofu approval history cannot be deleted'); END""")

    op.execute("""CREATE TRIGGER trg_opentofu_execution_scope_insert
        BEFORE INSERT ON opentofu_executions
        WHEN NOT EXISTS (
            SELECT 1 FROM opentofu_plans p
            JOIN opentofu_approvals a ON a.plan_id=p.plan_id AND a.plan_sha256=p.plan_sha256
            WHERE p.plan_id=NEW.plan_id AND p.plan_sha256=NEW.plan_sha256
              AND p.status='APPLYING'
        )
        BEGIN SELECT RAISE(ABORT, 'OpenTofu execution requires a hash-matched approved plan'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_execution_identity_immutable
        BEFORE UPDATE OF execution_id,plan_id,plan_sha256,started_at,executed_by
        ON opentofu_executions
        BEGIN SELECT RAISE(ABORT, 'OpenTofu execution identity is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_execution_state_transition
        BEFORE UPDATE OF status ON opentofu_executions
        WHEN NOT (OLD.status='RUNNING' AND NEW.status IN ('SUCCEEDED','FAILED'))
        BEGIN SELECT RAISE(ABORT, 'OpenTofu execution state transition is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_execution_final_immutable
        BEFORE UPDATE ON opentofu_executions
        WHEN OLD.status IN ('SUCCEEDED','FAILED')
        BEGIN SELECT RAISE(ABORT, 'OpenTofu execution evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_executions_no_delete
        BEFORE DELETE ON opentofu_executions
        BEGIN SELECT RAISE(ABORT, 'OpenTofu execution history cannot be deleted'); END""")

    bind = op.get_bind()
    permissions = (
        ("infrastructure.read", "infrastructure", "read", "View Project/Lab OpenTofu workspaces, plans and infrastructure state addresses"),
        ("infrastructure.manage", "infrastructure", "manage", "Create isolated OpenTofu workspaces and review plans"),
        ("infrastructure.approve", "infrastructure", "approve", "Independently approve immutable OpenTofu plans"),
        ("infrastructure.execute", "infrastructure", "execute", "Apply explicitly approved OpenTofu plans"),
        ("infrastructure.destroy", "infrastructure", "destroy", "Approve and apply OpenTofu resource destruction"),
    )
    for code, resource, action, description in permissions:
        bind.execute(
            sa.text("INSERT OR IGNORE INTO permissions(code,resource,action,description) VALUES(:code,:resource,:action,:description)"),
            {"code": code, "resource": resource, "action": action, "description": description},
        )
    grants = {
        "VIEWER": ("infrastructure.read",),
        "OPERATOR": ("infrastructure.read",),
        "ADMIN": ("infrastructure.read", "infrastructure.manage", "infrastructure.approve", "infrastructure.execute", "infrastructure.destroy"),
        "OWNER": ("infrastructure.read", "infrastructure.manage", "infrastructure.approve", "infrastructure.execute", "infrastructure.destroy"),
    }
    for scope in ("GLOBAL", "PROJECT"):
        for role_name, codes in grants.items():
            for permission in codes:
                bind.execute(
                    sa.text("INSERT OR IGNORE INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                    {"role": f"{scope.lower()}_{role_name.lower()}", "permission": permission},
                )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','31') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261124_21') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "OpenTofu state, plan, approval and execution evidence is audit-bearing; "
        "restore a verified pre-migration SQLite backup instead."
    )
