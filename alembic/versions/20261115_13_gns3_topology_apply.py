"""Add GNS3 Lab bindings, provider mappings and immutable apply history.

Revision ID: 20261115_13
Revises: 20261115_12
"""
from alembic import op
import sqlalchemy as sa

revision = "20261115_13"
down_revision = "20261115_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gns3_lab_bindings",
        sa.Column("binding_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=False),
        sa.Column("endpoint_url", sa.String(512), nullable=False),
        sa.Column("gns3_project_id", sa.String(128), nullable=False),
        sa.Column("controller_device_id", sa.String(), sa.ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("credential_id", sa.String(), sa.ForeignKey("managed_credentials.credential_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_gns3_lab_bindings_status"),
        sa.CheckConstraint("length(trim(gns3_project_id)) BETWEEN 1 AND 128", name="ck_gns3_lab_bindings_project"),
        sa.UniqueConstraint("lab_id", name="uq_gns3_binding_lab"),
    )
    op.create_index("idx_gns3_bindings_project_lab", "gns3_lab_bindings", ["project_id", "lab_id", "status"])
    op.execute(
        """CREATE TRIGGER trg_gns3_bindings_credential_scope_insert
           BEFORE INSERT ON gns3_lab_bindings
           WHEN NEW.status='ACTIVE' AND NOT EXISTS (
             SELECT 1 FROM managed_credentials c
             JOIN devices d ON d.device_id=c.device_id
             WHERE c.credential_id=NEW.credential_id
               AND c.project_id=NEW.project_id
               AND c.device_id=NEW.controller_device_id
               AND c.credential_type='API_TOKEN'
               AND c.status='ACTIVE'
               AND c.username IS NOT NULL
               AND d.project_id=NEW.project_id
               AND d.lab_id=NEW.lab_id
               AND d.status='ACTIVE'
           )
           BEGIN SELECT RAISE(ABORT, 'GNS3 binding credential scope mismatch'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_gns3_bindings_credential_scope_update
           BEFORE UPDATE OF project_id,lab_id,controller_device_id,credential_id,status ON gns3_lab_bindings
           WHEN NEW.status='ACTIVE' AND NOT EXISTS (
             SELECT 1 FROM managed_credentials c
             JOIN devices d ON d.device_id=c.device_id
             WHERE c.credential_id=NEW.credential_id
               AND c.project_id=NEW.project_id
               AND c.device_id=NEW.controller_device_id
               AND c.credential_type='API_TOKEN'
               AND c.status='ACTIVE'
               AND c.username IS NOT NULL
               AND d.project_id=NEW.project_id
               AND d.lab_id=NEW.lab_id
               AND d.status='ACTIVE'
           )
           BEGIN SELECT RAISE(ABORT, 'GNS3 binding credential scope mismatch'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_gns3_bindings_no_delete
           BEFORE DELETE ON gns3_lab_bindings
           BEGIN SELECT RAISE(ABORT, 'GNS3 bindings must be archived, not deleted'); END"""
    )

    op.create_table(
        "topology_provider_mappings",
        sa.Column("mapping_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("topology_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("resource_type", sa.String(8), nullable=False),
        sa.Column("logical_id", sa.String(64), nullable=False),
        sa.Column("provider_resource_id", sa.String(128), nullable=False),
        sa.Column("template_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("resource_type IN ('NODE','LINK')", name="ck_topology_provider_mappings_type"),
        sa.UniqueConstraint("profile_id", "resource_type", "logical_id", name="uq_topology_provider_mapping_logical"),
        sa.UniqueConstraint("profile_id", "resource_type", "provider_resource_id", name="uq_topology_provider_mapping_remote"),
    )
    op.create_index("idx_topology_provider_mappings_lab", "topology_provider_mappings", ["project_id", "lab_id", "profile_id"])
    op.execute(
        """CREATE TRIGGER trg_topology_provider_mappings_scope_insert
           BEFORE INSERT ON topology_provider_mappings
           WHEN NOT EXISTS (
             SELECT 1 FROM topology_profiles p
             WHERE p.profile_id=NEW.profile_id AND p.project_id=NEW.project_id
               AND p.scope_type='LAB' AND p.lab_id=NEW.lab_id AND p.status='ACTIVE'
           )
           BEGIN SELECT RAISE(ABORT, 'provider mapping must belong to an active Lab topology profile'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_topology_provider_mappings_scope_update
           BEFORE UPDATE OF project_id,lab_id,profile_id,resource_type,logical_id ON topology_provider_mappings
           WHEN NOT EXISTS (
             SELECT 1 FROM topology_profiles p
             WHERE p.profile_id=NEW.profile_id AND p.project_id=NEW.project_id
               AND p.scope_type='LAB' AND p.lab_id=NEW.lab_id AND p.status='ACTIVE'
           )
           BEGIN SELECT RAISE(ABORT, 'provider mapping must belong to an active Lab topology profile'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_topology_provider_mappings_no_delete
           BEFORE DELETE ON topology_provider_mappings
           BEGIN SELECT RAISE(ABORT, 'provider mappings are audit-bearing and cannot be deleted'); END"""
    )

    op.create_table(
        "topology_apply_records",
        sa.Column("apply_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("topology_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_id", sa.String(), sa.ForeignKey("topology_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("plan_json", sa.String(), nullable=False),
        sa.Column("observed_before_json", sa.String(), nullable=False),
        sa.Column("observed_after_json", sa.String(), nullable=False),
        sa.Column("result_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('APPLYING','APPLIED','PARTIAL','FAILED')", name="ck_topology_apply_status"),
        sa.CheckConstraint("length(content_sha256)=64", name="ck_topology_apply_hash"),
    )
    op.create_index("idx_topology_apply_lab_created", "topology_apply_records", ["project_id", "lab_id", "created_at"])
    op.create_index("idx_topology_apply_profile_revision", "topology_apply_records", ["profile_id", "revision_id"])
    op.execute(
        """CREATE TRIGGER trg_topology_apply_scope_insert
           BEFORE INSERT ON topology_apply_records
           WHEN NOT EXISTS (
             SELECT 1 FROM topology_profiles p
             JOIN topology_revisions r ON r.profile_id=p.profile_id
             WHERE p.profile_id=NEW.profile_id AND p.project_id=NEW.project_id
               AND p.scope_type='LAB' AND p.lab_id=NEW.lab_id
               AND r.revision_id=NEW.revision_id AND r.status='PUBLISHED'
               AND r.content_sha256=NEW.content_sha256
           )
           BEGIN SELECT RAISE(ABORT, 'apply record must reference a published revision in the same Lab'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_topology_apply_identity_immutable
           BEFORE UPDATE OF apply_id,project_id,lab_id,profile_id,revision_id,content_sha256,plan_json,created_at,started_at,created_by
           ON topology_apply_records
           BEGIN SELECT RAISE(ABORT, 'topology apply identity and plan are immutable'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_topology_apply_no_delete
           BEFORE DELETE ON topology_apply_records
           BEGIN SELECT RAISE(ABORT, 'topology apply history cannot be deleted'); END"""
    )


    op.create_table(
        "device_configuration_deployments",
        sa.Column("deployment_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=False),
        sa.Column("device_id", sa.String(), sa.ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("configuration_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_id", sa.String(), sa.ForeignKey("configuration_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("schema_record_id", sa.String(), sa.ForeignKey("configuration_schemas.schema_record_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("plan_json", sa.String(), nullable=False),
        sa.Column("result_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('APPLYING','APPLIED','PARTIAL','FAILED')", name="ck_device_config_deployments_status"),
        sa.CheckConstraint("length(configuration_hash)=64", name="ck_device_config_deployments_hash"),
    )
    op.create_index(
        "idx_device_config_deployments_target",
        "device_configuration_deployments",
        ["project_id", "lab_id", "device_id", "created_at"],
    )
    op.create_index(
        "idx_device_config_deployments_revision",
        "device_configuration_deployments",
        ["profile_id", "revision_id"],
    )
    op.execute(
        """CREATE TRIGGER trg_device_config_deployments_scope_insert
           BEFORE INSERT ON device_configuration_deployments
           WHEN NOT EXISTS (
             SELECT 1
             FROM configuration_profiles p
             JOIN configuration_revisions r ON r.profile_id=p.profile_id
             JOIN configuration_schemas s ON s.schema_record_id=NEW.schema_record_id
             JOIN devices d ON d.device_id=NEW.device_id
             JOIN labs l ON l.lab_id=NEW.lab_id AND l.project_id=NEW.project_id
             JOIN projects pr ON pr.project_id=NEW.project_id
             WHERE p.profile_id=NEW.profile_id
               AND p.project_id=NEW.project_id
               AND p.scope_type='DEVICE' AND p.scope_id=NEW.device_id
               AND p.status='PUBLISHED'
               AND r.revision_id=NEW.revision_id AND r.status='PUBLISHED'
               AND r.schema_record_id=NEW.schema_record_id
               AND r.configuration_hash=NEW.configuration_hash
               AND s.project_id=NEW.project_id
               AND s.schema_id='openwrt.wifi.v1' AND s.version=1 AND s.status='ACTIVE'
               AND d.project_id=NEW.project_id AND d.lab_id=NEW.lab_id
               AND d.status='ACTIVE' AND upper(d.vendor)='OPENWRT'
               AND d.device_type='ROUTER'
               AND l.status='ACTIVE' AND pr.status='ACTIVE'
           )
           BEGIN SELECT RAISE(ABORT, 'device configuration deployment scope or adapter mismatch'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_device_config_deployments_identity_immutable
           BEFORE UPDATE OF deployment_id,project_id,lab_id,device_id,profile_id,revision_id,
             schema_record_id,configuration_hash,plan_json,created_at,started_at,created_by
           ON device_configuration_deployments
           BEGIN SELECT RAISE(ABORT, 'device configuration deployment identity and plan are immutable'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_device_config_deployments_final_immutable
           BEFORE UPDATE ON device_configuration_deployments
           WHEN OLD.status<>'APPLYING'
             OR NEW.status NOT IN ('APPLIED','PARTIAL','FAILED')
             OR NEW.completed_at IS NULL
           BEGIN SELECT RAISE(ABORT, 'completed device configuration deployment is immutable'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_device_config_deployments_no_delete
           BEFORE DELETE ON device_configuration_deployments
           BEGIN SELECT RAISE(ABORT, 'device configuration deployment evidence cannot be deleted'); END"""
    )

    bind = op.get_bind()
    permissions = (
        ("topology.provider.manage", "topology", "provider_manage", "Bind and inspect a Project/Lab GNS3 provider"),
        ("topology.provider.operate", "topology", "provider_operate", "Explicitly start or stop mapped provider nodes"),
        ("topology.apply", "topology", "apply", "Apply a published topology revision to its bound Lab"),
        ("configurations.deploy", "configurations", "deploy", "Deploy allow-listed published configuration revisions to supported Devices"),
    )
    for code, resource, action, description in permissions:
        bind.execute(
            sa.text("INSERT OR IGNORE INTO permissions(code,resource,action,description) VALUES(:code,:resource,:action,:description)"),
            {"code": code, "resource": resource, "action": action, "description": description},
        )
    for scope in ("GLOBAL", "PROJECT"):
        for role_name in ("ADMIN", "OWNER"):
            for permission in ("topology.provider.manage", "topology.provider.operate", "topology.apply", "configurations.deploy"):
                bind.execute(
                    sa.text("INSERT OR IGNORE INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                    {"role": f"{scope.lower()}_{role_name.lower()}", "permission": permission},
                )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','23') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261115_13') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "GNS3 bindings, topology mappings and apply evidence are audit-bearing. "
        "Restore a verified pre-migration backup instead of destructively downgrading."
    )
