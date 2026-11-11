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
        sa.Column(
            "project_id",
            sa.String(),
            sa.ForeignKey("projects.project_id", ondelete="RESTRICT"),
            nullable=True,
        ),
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
