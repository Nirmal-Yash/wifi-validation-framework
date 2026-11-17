"""Enforce Project/Lab scope when associating a Run after pipeline creation.

Revision ID: 20261117_15
Revises: 20261116_14
"""
from alembic import op

revision = "20261117_15"
down_revision = "20261116_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TRIGGER trg_pipeline_execution_run_scope_update
        BEFORE UPDATE OF linked_run_id ON pipeline_executions
        WHEN NEW.linked_run_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM runs r WHERE r.run_id=NEW.linked_run_id
            AND r.project_id=NEW.project_id AND r.lab_id=NEW.lab_id
        )
        BEGIN SELECT RAISE(ABORT, 'pipeline Run link must belong to the same Project/Lab'); END""")
    bind = op.get_bind()
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('version','25') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261117_15') ON CONFLICT(key) DO UPDATE SET value=excluded.value")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_pipeline_execution_run_scope_update")
    bind = op.get_bind()
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('version','24') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261116_14') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
