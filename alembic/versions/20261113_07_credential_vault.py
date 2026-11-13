"""Add Stage C credential metadata; secret material stays in OS vaults.

Revision ID: 20261113_07
Revises: 20261113_06
"""
from alembic import op
import sqlalchemy as sa

revision = "20261113_07"
down_revision = "20261113_06"
branch_labels = None
depends_on = None

CREDENTIAL_PERMISSIONS = (
    ("credentials.read", "credentials", "read", "View credential metadata and verification status"),
    ("credentials.manage", "credentials", "manage", "Create, rotate and revoke stored credentials"),
    ("credentials.verify", "credentials", "verify", "Verify a credential against its assigned device"),
)


def upgrade() -> None:
    op.create_table(
        "managed_credentials",
        sa.Column("credential_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("credential_type", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("secret_provider", sa.String(), nullable=False),
        sa.Column("secret_reference", sa.String(), nullable=False, unique=True),
        sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
        sa.Column("verification_status", sa.String(), nullable=False, server_default="NOT_VERIFIED"),
        sa.Column("last_verified_at", sa.String(), nullable=True),
        sa.Column("verification_summary", sa.String(), nullable=True),
        sa.Column("rotated_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.CheckConstraint(
            "credential_type IN ('SSH_PASSWORD','SSH_PRIVATE_KEY','WIFI_PSK','API_TOKEN')",
            name="ck_managed_credentials_type",
        ),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name="ck_managed_credentials_status"),
        sa.CheckConstraint(
            "verification_status IN ('NOT_VERIFIED','VERIFIED','FAILED','UNAVAILABLE')",
            name="ck_managed_credentials_verification",
        ),
        sa.CheckConstraint("length(trim(label)) BETWEEN 1 AND 120", name="ck_managed_credentials_label"),
        sa.UniqueConstraint("project_id", "device_id", "label", name="uq_credentials_project_device_label"),
    )
    op.create_index(
        "idx_credentials_project_device_status",
        "managed_credentials",
        ["project_id", "device_id", "status"],
    )
    op.execute(
        """CREATE TRIGGER trg_managed_credentials_no_delete
           BEFORE DELETE ON managed_credentials
           BEGIN SELECT RAISE(ABORT, 'managed credentials must be revoked, not deleted'); END"""
    )
    bind = op.get_bind()
    for code, resource, action, description in CREDENTIAL_PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO permissions(code,resource,action,description) "
                "VALUES(:code,:resource,:action,:description)"
            ),
            {"code": code, "resource": resource, "action": action, "description": description},
        )
    grants = {
        "VIEWER": ("credentials.read",),
        "OPERATOR": ("credentials.read", "credentials.verify"),
        "ADMIN": ("credentials.read", "credentials.manage", "credentials.verify"),
        "OWNER": ("credentials.read", "credentials.manage", "credentials.verify"),
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
        "INSERT INTO schema_meta(key,value) VALUES ('version','16') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES ('alembic_revision','20261113_07') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Credential metadata and audit history must not be destructively downgraded. "
        "Restore a verified pre-migration SQLite backup instead."
    )
