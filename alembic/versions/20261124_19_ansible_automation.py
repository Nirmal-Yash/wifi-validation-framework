"""Add approval-gated, Project/Lab-scoped Ansible deployment plans.

Revision ID: 20261124_19
Revises: 20261123_18
"""
from alembic import op
import sqlalchemy as sa

revision = "20261124_19"
down_revision = "20261123_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ansible_automation_plans",
        sa.Column("plan_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("network_intent_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_id", sa.String(), sa.ForeignKey("network_intent_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("approved_at", sa.String(), nullable=True),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('PREVIEWED','BLOCKED','APPROVED','STALE','EXECUTING','SUCCEEDED','FAILED')", name="ck_ansible_automation_plans_status"),
        sa.CheckConstraint("length(plan_sha256)=64 AND plan_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_ansible_automation_plans_hash"),
        sa.CheckConstraint("length(plan_json) BETWEEN 2 AND 5000000", name="ck_ansible_automation_plans_json_size"),
        sa.CheckConstraint("length(validation_json) BETWEEN 2 AND 32768", name="ck_ansible_automation_plans_validation_size"),
        sa.CheckConstraint("(status IN ('APPROVED','STALE','EXECUTING','SUCCEEDED','FAILED') AND approved_at IS NOT NULL AND approved_by IS NOT NULL) OR (status IN ('PREVIEWED','BLOCKED') AND approved_at IS NULL AND approved_by IS NULL)", name="ck_ansible_automation_plans_approval"),
    )
    op.create_index(
        "idx_ansible_automation_plans_project_created",
        "ansible_automation_plans", ["project_id", "created_at"],
    )
    op.create_index(
        "idx_ansible_automation_plans_revision",
        "ansible_automation_plans", ["revision_id", "created_at"],
    )

    op.create_table(
        "ansible_automation_approvals",
        sa.Column("approval_id", sa.String(32), primary_key=True),
        sa.Column("plan_id", sa.String(32), sa.ForeignKey("ansible_automation_plans.plan_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column("confirmed_at", sa.String(), nullable=False),
        sa.CheckConstraint("length(plan_sha256)=64 AND plan_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_ansible_automation_approvals_hash"),
        sa.UniqueConstraint("plan_id", "plan_sha256", name="uq_ansible_automation_approval_hash"),
    )
    op.create_index(
        "idx_ansible_automation_approvals_plan",
        "ansible_automation_approvals", ["plan_id", "confirmed_at"],
    )

    op.create_table(
        "ansible_automation_executions",
        sa.Column("execution_id", sa.String(32), primary_key=True),
        sa.Column("plan_id", sa.String(32), sa.ForeignKey("ansible_automation_plans.plan_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approval_id", sa.String(32), sa.ForeignKey("ansible_automation_approvals.approval_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("executed_by", sa.String(128), nullable=False),
        sa.CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED')", name="ck_ansible_automation_executions_status"),
        sa.CheckConstraint("length(plan_sha256)=64 AND plan_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_ansible_automation_executions_hash"),
        sa.CheckConstraint("length(result_json) BETWEEN 2 AND 131072", name="ck_ansible_automation_executions_result_size"),
        sa.CheckConstraint("(status='RUNNING' AND completed_at IS NULL) OR (status IN ('SUCCEEDED','FAILED') AND completed_at IS NOT NULL)", name="ck_ansible_automation_executions_completion"),
    )
    op.create_index(
        "idx_ansible_automation_executions_plan",
        "ansible_automation_executions", ["plan_id", "started_at"],
    )

    op.execute("""CREATE TRIGGER trg_ansible_automation_plans_scope_insert
        BEFORE INSERT ON ansible_automation_plans
        WHEN NOT EXISTS (
            SELECT 1 FROM network_intent_profiles p
            JOIN network_intent_revisions r ON r.revision_id=NEW.revision_id
            WHERE p.profile_id=NEW.profile_id
              AND p.project_id=NEW.project_id
              AND COALESCE(p.lab_id,'')=COALESCE(NEW.lab_id,'')
              AND p.status='ACTIVE'
              AND r.profile_id=p.profile_id
              AND r.status='PUBLISHED'
        )
        BEGIN SELECT RAISE(ABORT, 'Ansible plan must bind a published Network Intent revision in the same Project/Lab scope'); END""")
    op.execute("""CREATE TRIGGER trg_ansible_automation_plans_identity_immutable
        BEFORE UPDATE OF plan_id,project_id,lab_id,profile_id,revision_id,plan_sha256,plan_json,
          validation_json,created_at,created_by
        ON ansible_automation_plans
        BEGIN SELECT RAISE(ABORT, 'Ansible automation plan content is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_ansible_automation_plans_state_transition
        BEFORE UPDATE OF status ON ansible_automation_plans
        WHEN NOT (
            OLD.status=NEW.status
            OR (OLD.status='PREVIEWED' AND NEW.status='APPROVED')
            OR (OLD.status='APPROVED' AND NEW.status IN ('EXECUTING','STALE'))
            OR (OLD.status='EXECUTING' AND NEW.status IN ('SUCCEEDED','FAILED'))
        )
        BEGIN SELECT RAISE(ABORT, 'Ansible automation plan state transition is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_ansible_automation_plans_no_delete
        BEFORE DELETE ON ansible_automation_plans
        BEGIN SELECT RAISE(ABORT, 'Ansible automation plan history cannot be deleted'); END""")

    op.execute("""CREATE TRIGGER trg_ansible_automation_plans_approval_immutable
        BEFORE UPDATE OF approved_at,approved_by ON ansible_automation_plans
        WHEN OLD.status <> 'PREVIEWED'
        BEGIN SELECT RAISE(ABORT, 'Ansible plan approval identity is immutable'); END""")

    op.execute("""CREATE TRIGGER trg_ansible_automation_approvals_scope_insert
        BEFORE INSERT ON ansible_automation_approvals
        WHEN NOT EXISTS (
            SELECT 1 FROM ansible_automation_plans p
            WHERE p.plan_id=NEW.plan_id
              AND p.plan_sha256=NEW.plan_sha256
              AND p.status='PREVIEWED'
        )
        BEGIN SELECT RAISE(ABORT, 'Ansible approval must match a validated previewed plan hash'); END""")
    op.execute("""CREATE TRIGGER trg_ansible_automation_approvals_immutable
        BEFORE UPDATE ON ansible_automation_approvals
        BEGIN SELECT RAISE(ABORT, 'Ansible approval evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_ansible_automation_approvals_no_delete
        BEFORE DELETE ON ansible_automation_approvals
        BEGIN SELECT RAISE(ABORT, 'Ansible approval history cannot be deleted'); END""")

    op.execute("""CREATE TRIGGER trg_ansible_automation_executions_scope_insert
        BEFORE INSERT ON ansible_automation_executions
        WHEN NOT EXISTS (
            SELECT 1 FROM ansible_automation_plans p
            JOIN ansible_automation_approvals a ON a.approval_id=NEW.approval_id
            WHERE p.plan_id=NEW.plan_id
              AND p.plan_sha256=NEW.plan_sha256
              AND p.status='EXECUTING'
              AND a.plan_id=p.plan_id
              AND a.plan_sha256=p.plan_sha256
        )
        BEGIN SELECT RAISE(ABORT, 'Ansible execution requires an approved, hash-matched plan'); END""")
    op.execute("""CREATE TRIGGER trg_ansible_automation_executions_identity_immutable
        BEFORE UPDATE OF execution_id,plan_id,approval_id,plan_sha256,started_at,executed_by
        ON ansible_automation_executions
        BEGIN SELECT RAISE(ABORT, 'Ansible execution identity is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_ansible_automation_executions_state_transition
        BEFORE UPDATE OF status ON ansible_automation_executions
        WHEN NOT (OLD.status='RUNNING' AND NEW.status IN ('SUCCEEDED','FAILED'))
        BEGIN SELECT RAISE(ABORT, 'Ansible execution state transition is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_ansible_automation_executions_no_delete
        BEFORE DELETE ON ansible_automation_executions
        BEGIN SELECT RAISE(ABORT, 'Ansible execution history cannot be deleted'); END""")

    op.execute("""CREATE TRIGGER trg_ansible_automation_executions_final_immutable
        BEFORE UPDATE ON ansible_automation_executions
        WHEN OLD.status IN ('SUCCEEDED','FAILED')
        BEGIN SELECT RAISE(ABORT, 'Ansible execution result evidence is immutable'); END""")

    bind = op.get_bind()
    permissions = (
        ("network_automation.read", "network_automation", "read", "View approved Ansible automation plans and execution evidence"),
        ("network_automation.manage", "network_automation", "manage", "Create and validate scoped Ansible automation plans"),
        ("network_automation.approve", "network_automation", "approve", "Approve hash-pinned Ansible automation plans"),
        ("network_automation.execute", "network_automation", "execute", "Execute approved Ansible automation plans and verify read-back"),
    )
    for code, resource, action, description in permissions:
        bind.execute(
            sa.text("INSERT OR IGNORE INTO permissions(code,resource,action,description) VALUES(:code,:resource,:action,:description)"),
            {"code": code, "resource": resource, "action": action, "description": description},
        )
    grants = {
        "VIEWER": ("network_automation.read",),
        "OPERATOR": ("network_automation.read",),
        "ADMIN": ("network_automation.read", "network_automation.manage", "network_automation.approve", "network_automation.execute"),
        "OWNER": ("network_automation.read", "network_automation.manage", "network_automation.approve", "network_automation.execute"),
    }
    for scope in ("GLOBAL", "PROJECT"):
        for role_name, codes in grants.items():
            for permission in codes:
                bind.execute(
                    sa.text("INSERT OR IGNORE INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                    {"role": f"{scope.lower()}_{role_name.lower()}", "permission": permission},
                )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','29') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261124_19') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Ansible plan, approval and execution evidence is audit-bearing; "
        "restore a verified pre-migration SQLite backup instead."
    )
