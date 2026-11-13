"""Add Project-scoped typed configuration schema registry.

Revision ID: 20261113_08
Revises: 20261113_07
"""
from alembic import op
import sqlalchemy as sa

revision = "20261113_08"
down_revision = "20261113_07"
branch_labels = None
depends_on = None

CONFIG_PERMISSIONS = (
    ("configurations.read", "configurations", "read", "View registered schemas and managed configuration"),
    ("configurations.manage", "configurations", "manage", "Register schemas and manage configuration profiles"),
    ("configurations.publish", "configurations", "publish", "Publish and assign configuration revisions"),
)


def upgrade() -> None:
    op.create_table(
        "configuration_schemas",
        sa.Column("schema_record_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("schema_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("definition_json", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_configuration_schemas_version"),
        sa.CheckConstraint("status IN ('ACTIVE','DEPRECATED')", name="ck_configuration_schemas_status"),
        sa.CheckConstraint("length(trim(schema_id)) BETWEEN 1 AND 128", name="ck_configuration_schemas_id"),
        sa.UniqueConstraint("project_id", "schema_id", "version", name="uq_configuration_schema_version"),
    )
    op.create_index(
        "idx_configuration_schemas_project_schema",
        "configuration_schemas",
        ["project_id", "schema_id", "version"],
    )
    op.execute(
        """CREATE TRIGGER trg_configuration_schemas_no_delete
           BEFORE DELETE ON configuration_schemas
           BEGIN SELECT RAISE(ABORT, 'configuration schemas are versioned and cannot be deleted'); END"""
    )
    bind = op.get_bind()
    for code, resource, action, description in CONFIG_PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO permissions(code,resource,action,description) "
                "VALUES(:code,:resource,:action,:description)"
            ),
            {"code": code, "resource": resource, "action": action, "description": description},
        )
    grants = {
        "VIEWER": ("configurations.read",),
        "OPERATOR": ("configurations.read",),
        "ADMIN": ("configurations.read", "configurations.manage", "configurations.publish"),
        "OWNER": ("configurations.read", "configurations.manage", "configurations.publish"),
    }
    for scope in ("GLOBAL", "PROJECT"):
        for role_name, codes in grants.items():
            role_id = f"{scope.lower()}_{role_name.lower()}"
            for code in codes:
                bind.execute(
                    sa.text(
                        "INSERT INTO role_permissions(role_id,permission_code) "
                        "VALUES(:role,:permission)"
                    ),
                    {"role": role_id, "permission": code},
                )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES ('version','17') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES ('alembic_revision','20261113_08') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Configuration schema history must not be destructively downgraded. "
        "Restore a verified pre-migration SQLite backup instead."
    )
