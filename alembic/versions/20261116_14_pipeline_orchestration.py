"""Persist versioned pipelines, execution state and worker recovery history.

Revision ID: 20261116_14
Revises: 20261115_13
"""
from alembic import op
import sqlalchemy as sa

revision = "20261116_14"
down_revision = "20261115_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_definitions",
        sa.Column("pipeline_id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("lab_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_pipeline_definitions_status"),
        sa.UniqueConstraint("project_id", "lab_id", "name", name="uq_pipeline_definitions_scope_name"),
    )
    op.create_index("idx_pipeline_definitions_project_lab", "pipeline_definitions", ["project_id", "lab_id", "status"])

    op.create_table(
        "pipeline_revisions",
        sa.Column("revision_id", sa.String(64), primary_key=True),
        sa.Column("pipeline_id", sa.String(64), sa.ForeignKey("pipeline_definitions.pipeline_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("definition_json", sa.String(), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("published_at", sa.String(), nullable=True),
        sa.Column("published_by", sa.String(128), nullable=True),
        sa.CheckConstraint("revision_number >= 1", name="ck_pipeline_revisions_number"),
        sa.CheckConstraint("length(definition_sha256)=64", name="ck_pipeline_revisions_hash"),
        sa.CheckConstraint("status IN ('DRAFT','PUBLISHED')", name="ck_pipeline_revisions_status"),
        sa.UniqueConstraint("pipeline_id", "revision_number", name="uq_pipeline_revisions_number"),
    )
    op.create_index("idx_pipeline_revisions_pipeline_number", "pipeline_revisions", ["pipeline_id", "revision_number"])

    op.create_table(
        "pipeline_executions",
        sa.Column("execution_id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("lab_id", sa.String(128), nullable=False),
        sa.Column("pipeline_id", sa.String(64), sa.ForeignKey("pipeline_definitions.pipeline_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_id", sa.String(64), sa.ForeignKey("pipeline_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="QUEUED"),
        sa.Column("inputs_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("linked_run_id", sa.String(), sa.ForeignKey("runs.run_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column("heartbeat_at", sa.String(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.CheckConstraint("status IN ('QUEUED','RUNNING','CANCELLING','SUCCEEDED','FAILED','PARTIAL','CANCELLED','RECOVERY_REQUIRED')", name="ck_pipeline_executions_status"),
        sa.CheckConstraint("length(definition_sha256)=64", name="ck_pipeline_executions_hash"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_pipeline_executions_attempts"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_pipeline_executions_idempotency"),
    )
    op.create_index("idx_pipeline_executions_queue", "pipeline_executions", ["status", "lease_expires_at", "created_at"])
    op.create_index("idx_pipeline_executions_project_lab", "pipeline_executions", ["project_id", "lab_id", "created_at"])
    op.create_index("idx_pipeline_executions_pipeline", "pipeline_executions", ["pipeline_id", "created_at"])
    op.create_index("idx_pipeline_executions_linked_run", "pipeline_executions", ["linked_run_id"])

    op.create_table(
        "pipeline_steps",
        sa.Column("execution_id", sa.String(64), sa.ForeignKey("pipeline_executions.execution_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("step_key", sa.String(64), primary_key=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("definition_json", sa.String(), nullable=False),
        sa.Column("result_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("next_attempt_at", sa.String(), nullable=True),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.CheckConstraint("ordinal >= 0", name="ck_pipeline_steps_ordinal"),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','RETRY_WAIT','SUCCEEDED','FAILED','SKIPPED','CANCELLED','RECOVERY_REQUIRED')", name="ck_pipeline_steps_status"),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 5", name="ck_pipeline_steps_max_attempts"),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 5", name="ck_pipeline_steps_attempts"),
        sa.CheckConstraint("timeout_seconds BETWEEN 5 AND 3600", name="ck_pipeline_steps_timeout"),
        sa.UniqueConstraint("execution_id", "ordinal", name="uq_pipeline_steps_ordinal"),
    )
    op.create_index("idx_pipeline_steps_ready", "pipeline_steps", ["execution_id", "status", "ordinal"])

    op.create_table(
        "pipeline_step_attempts",
        sa.Column("step_attempt_id", sa.String(64), primary_key=True),
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("step_key", sa.String(64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("result_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("error_summary", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(["execution_id", "step_key"], ["pipeline_steps.execution_id", "pipeline_steps.step_key"], ondelete="RESTRICT"),
        sa.CheckConstraint("attempt_number BETWEEN 1 AND 5", name="ck_pipeline_step_attempt_number"),
        sa.CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED','RETRY_WAIT','RECOVERY_REQUIRED','CANCELLED')", name="ck_pipeline_step_attempt_status"),
        sa.UniqueConstraint("execution_id", "step_key", "attempt_number", name="uq_pipeline_step_attempt_number"),
    )
    op.create_index("idx_pipeline_step_attempts_step", "pipeline_step_attempts", ["execution_id", "step_key", "attempt_number"])

    op.execute("""CREATE TRIGGER trg_pipeline_definitions_no_delete
        BEFORE DELETE ON pipeline_definitions
        BEGIN SELECT RAISE(ABORT, 'pipeline definitions are audit-bearing and cannot be deleted'); END""")
    op.execute("""CREATE TRIGGER trg_pipeline_revisions_published_immutable
        BEFORE UPDATE ON pipeline_revisions WHEN OLD.status='PUBLISHED'
        BEGIN SELECT RAISE(ABORT, 'published pipeline revisions are immutable'); END""")
    op.execute("""CREATE TRIGGER trg_pipeline_revisions_no_delete
        BEFORE DELETE ON pipeline_revisions
        BEGIN SELECT RAISE(ABORT, 'pipeline revision history cannot be deleted'); END""")
    op.execute("""CREATE TRIGGER trg_pipeline_execution_scope_insert
        BEFORE INSERT ON pipeline_executions
        WHEN NOT EXISTS (
          SELECT 1 FROM pipeline_definitions d
          JOIN pipeline_revisions r ON r.pipeline_id=d.pipeline_id
          WHERE d.pipeline_id=NEW.pipeline_id AND d.project_id=NEW.project_id
            AND d.lab_id=NEW.lab_id AND d.status='ACTIVE'
            AND r.revision_id=NEW.revision_id AND r.definition_sha256=NEW.definition_sha256
            AND r.status='PUBLISHED'
        )
        BEGIN SELECT RAISE(ABORT, 'pipeline execution must target a published revision in the same Project/Lab'); END""")
    op.execute("""CREATE TRIGGER trg_pipeline_execution_run_scope_insert
        BEFORE INSERT ON pipeline_executions
        WHEN NEW.linked_run_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM runs r WHERE r.run_id=NEW.linked_run_id
            AND r.project_id=NEW.project_id AND r.lab_id=NEW.lab_id
        )
        BEGIN SELECT RAISE(ABORT, 'pipeline Run link must belong to the same Project/Lab'); END""")
    op.execute("""CREATE TRIGGER trg_pipeline_execution_identity_immutable
        BEFORE UPDATE OF execution_id,project_id,lab_id,pipeline_id,revision_id,definition_sha256,inputs_json,created_at,created_by
        ON pipeline_executions
        BEGIN SELECT RAISE(ABORT, 'pipeline execution identity and inputs are immutable'); END""")
    op.execute("""CREATE TRIGGER trg_pipeline_executions_no_delete
        BEFORE DELETE ON pipeline_executions
        BEGIN SELECT RAISE(ABORT, 'pipeline execution history cannot be deleted'); END""")
    op.execute("""CREATE TRIGGER trg_pipeline_steps_identity_immutable
        BEFORE UPDATE OF execution_id,step_key,ordinal,step_type,definition_json,max_attempts,timeout_seconds,created_at
        ON pipeline_steps
        BEGIN SELECT RAISE(ABORT, 'pipeline step definition is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_pipeline_steps_no_delete
        BEFORE DELETE ON pipeline_steps
        BEGIN SELECT RAISE(ABORT, 'pipeline step history cannot be deleted'); END""")
    op.execute("""CREATE TRIGGER trg_pipeline_step_attempts_final_immutable
        BEFORE UPDATE ON pipeline_step_attempts WHEN OLD.status<>'RUNNING'
        BEGIN SELECT RAISE(ABORT, 'completed pipeline step attempts are immutable'); END""")
    op.execute("""CREATE TRIGGER trg_pipeline_step_attempts_no_delete
        BEFORE DELETE ON pipeline_step_attempts
        BEGIN SELECT RAISE(ABORT, 'pipeline step attempt history cannot be deleted'); END""")

    bind = op.get_bind()
    permissions = (
        ("pipelines.read", "pipelines", "read", "View Project/Lab pipeline definitions and execution history"),
        ("pipelines.manage", "pipelines", "manage", "Create, publish and recover Project/Lab pipelines"),
        ("pipelines.execute", "pipelines", "execute", "Queue and cancel Project/Lab pipeline executions"),
    )
    for code, resource, action, description in permissions:
        bind.execute(
            sa.text("INSERT OR IGNORE INTO permissions(code,resource,action,description) VALUES(:code,:resource,:action,:description)"),
            {"code": code, "resource": resource, "action": action, "description": description},
        )
    grants = {
        "VIEWER": ("pipelines.read",),
        "OPERATOR": ("pipelines.read", "pipelines.execute"),
        "ADMIN": ("pipelines.read", "pipelines.manage", "pipelines.execute"),
        "OWNER": ("pipelines.read", "pipelines.manage", "pipelines.execute"),
    }
    for scope in ("GLOBAL", "PROJECT"):
        for role_name, codes in grants.items():
            for permission in codes:
                bind.execute(
                    sa.text("INSERT OR IGNORE INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                    {"role": f"{scope.lower()}_{role_name.lower()}", "permission": permission},
                )

    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('version','24') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261116_14') ON CONFLICT(key) DO UPDATE SET value=excluded.value")


def downgrade() -> None:
    raise RuntimeError("Pipeline definitions and execution records are audit-bearing; restore a verified pre-migration SQLite backup instead.")
