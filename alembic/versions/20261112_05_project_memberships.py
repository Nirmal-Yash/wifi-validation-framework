"""Persist project memberships and Run ownership.

Revision ID: 20261112_05
Revises: 20261111_04
"""
from alembic import op
import sqlalchemy as sa

revision = "20261112_05"
down_revision = "20261111_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("project_id", sa.String(), nullable=True),
    )
    op.create_index("idx_runs_project_created", "runs", ["project_id", "created_at"])
    op.create_table(
        "project_memberships",
        sa.Column("username", sa.String(), nullable=False),
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("username", "project_id", name="pk_project_memberships"),
        sa.CheckConstraint(
            "role IN ('OWNER', 'ADMIN', 'OPERATOR', 'VIEWER')",
            name="ck_project_memberships_role",
        ),
    )
    op.create_index(
        "idx_project_memberships_project",
        "project_memberships",
        ["project_id", "username"],
    )

    bind = op.get_bind()
    # SQLite cannot ALTER an existing column to add a foreign key without
    # rebuilding the full runs table. Triggers enforce Project and Lab ownership
    # at the database boundary without touching existing Runner rows.
    bind.exec_driver_sql(
        """
        CREATE TRIGGER trg_runs_project_scope_insert
        BEFORE INSERT ON runs
        WHEN NEW.project_id IS NOT NULL
        BEGIN
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM projects WHERE project_id = NEW.project_id
                )
                THEN RAISE(ABORT, 'run references an unknown project')
            END;
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM labs
                    WHERE lab_id = NEW.lab_id AND project_id = NEW.project_id
                )
                THEN RAISE(ABORT, 'run lab must belong to its project')
            END;
        END
        """
    )
    bind.exec_driver_sql(
        """
        CREATE TRIGGER trg_runs_project_scope_update
        BEFORE UPDATE OF project_id, lab_id ON runs
        WHEN NEW.project_id IS NOT NULL
        BEGIN
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM projects WHERE project_id = NEW.project_id
                )
                THEN RAISE(ABORT, 'run references an unknown project')
            END;
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM labs
                    WHERE lab_id = NEW.lab_id AND project_id = NEW.project_id
                )
                THEN RAISE(ABORT, 'run lab must belong to its project')
            END;
        END
        """
    )
    bind.exec_driver_sql(
        """
        CREATE TRIGGER trg_projects_prevent_delete_with_runs
        BEFORE DELETE ON projects
        WHEN EXISTS (
            SELECT 1 FROM runs WHERE project_id = OLD.project_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'project still owns validation runs');
        END
        """
    )
    bind.exec_driver_sql(
        """
        INSERT INTO schema_meta(key, value) VALUES ('version', '14')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )
    bind.exec_driver_sql(
        """
        INSERT INTO schema_meta(key, value) VALUES ('alembic_revision', '20261112_05')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Project ownership schema is not destructively reversible. "
        "Restore a verified pre-migration SQLite backup instead."
    )
