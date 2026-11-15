"""Add Project/Lab-scoped managed device inventory.

Revision ID: 20261115_11
Revises: 20261113_10
"""
from alembic import op
import sqlalchemy as sa

revision = "20261115_11"
down_revision = "20261113_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite parent key makes cross-Project Lab references impossible.
    op.create_index("uq_labs_project_lab", "labs", ["project_id", "lab_id"], unique=True)
    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=False),
        sa.Column("device_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("device_type", sa.String(24), nullable=False),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="22"),
        sa.Column("vendor", sa.String(80), nullable=True),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("username", sa.String(128), nullable=True),
        sa.Column("credential_id", sa.String(), sa.ForeignKey("managed_credentials.credential_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("capabilities_json", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("device_type IN ('ROUTER','ACCESS_POINT','CLIENT','MONITOR','SWITCH','SERVER','OTHER')", name="ck_devices_type"),
        sa.CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_devices_status"),
        sa.CheckConstraint("port BETWEEN 1 AND 65535", name="ck_devices_port"),
        sa.CheckConstraint("length(trim(device_key)) BETWEEN 1 AND 64", name="ck_devices_key"),
        sa.UniqueConstraint("project_id", "lab_id", "device_key", name="uq_devices_lab_key"),
    )
    op.create_index("idx_devices_project_lab_status", "devices", ["project_id", "lab_id", "status"])
    op.create_index("idx_devices_credential", "devices", ["credential_id"])
    op.execute(
        """CREATE TRIGGER trg_devices_credential_scope_insert
           BEFORE INSERT ON devices
           WHEN NEW.credential_id IS NOT NULL AND NOT EXISTS (
             SELECT 1 FROM managed_credentials c
             WHERE c.credential_id=NEW.credential_id
               AND c.project_id=NEW.project_id
               AND c.device_id=NEW.device_id
               AND c.status='ACTIVE'
           )
           BEGIN SELECT RAISE(ABORT, 'device credential scope mismatch'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_devices_credential_scope_update
           BEFORE UPDATE OF credential_id,project_id,lab_id ON devices
           WHEN NEW.credential_id IS NOT NULL AND NOT EXISTS (
             SELECT 1 FROM managed_credentials c
             WHERE c.credential_id=NEW.credential_id
               AND c.project_id=NEW.project_id
               AND c.device_id=NEW.device_id
               AND c.status='ACTIVE'
           )
           BEGIN SELECT RAISE(ABORT, 'device credential scope mismatch'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_devices_no_delete
           BEFORE DELETE ON devices
           BEGIN SELECT RAISE(ABORT, 'devices must be archived, not deleted'); END"""
    )

    bind = op.get_bind()
    permissions = (
        ("devices.read", "devices", "read", "View Project/Lab device inventory"),
        ("devices.manage", "devices", "manage", "Create and update device inventory records"),
        ("devices.operate", "devices", "operate", "Run explicit device connectivity and health operations"),
    )
    for code, resource, action, description in permissions:
        bind.execute(
            sa.text("INSERT OR IGNORE INTO permissions(code,resource,action,description) VALUES(:code,:resource,:action,:description)"),
            {"code": code, "resource": resource, "action": action, "description": description},
        )
    grants = {
        "VIEWER": ("devices.read",),
        "OPERATOR": ("devices.read",),
        "ADMIN": ("devices.read", "devices.manage", "devices.operate"),
        "OWNER": ("devices.read", "devices.manage", "devices.operate"),
    }
    for scope in ("GLOBAL", "PROJECT"):
        for role_name, codes in grants.items():
            for permission in codes:
                bind.execute(
                    sa.text("INSERT OR IGNORE INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                    {"role": f"{scope.lower()}_{role_name.lower()}", "permission": permission},
                )
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('version','20') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261115_11') ON CONFLICT(key) DO UPDATE SET value=excluded.value")


def downgrade() -> None:
    raise RuntimeError("Managed device inventory is audit-bearing; restore a verified pre-migration SQLite backup instead.")
