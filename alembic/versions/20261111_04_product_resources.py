"""Additive organization, project and lab ownership foundation.

Revision ID: 20261111_04
Revises: 20261105_03
"""
from alembic import op
import sqlalchemy as sa

revision = "20261111_04"
down_revision = "20261105_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("organization_id", sa.String(), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.organization_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("organization_id", "slug", name="uq_projects_organization_slug"),
    )
    op.create_table(
        "labs",
        sa.Column("lab_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("topology_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("project_id", "name", name="uq_labs_project_name"),
    )
    op.create_index("idx_projects_organization", "projects", ["organization_id"])
    op.create_index("idx_labs_project", "labs", ["project_id"])

    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        INSERT INTO schema_meta(key, value) VALUES ('version', '13')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )
    bind.exec_driver_sql(
        """
        INSERT INTO schema_meta(key, value) VALUES ('alembic_revision', '20261111_04')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Product resource schema is not destructively reversible. "
        "Restore a verified pre-migration SQLite backup instead."
    )
