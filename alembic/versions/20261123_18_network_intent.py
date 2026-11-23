"""Add canonical, versioned network intent and immutable device capability reports.

Revision ID: 20261123_18
Revises: 20261123_17
"""
from alembic import op
import sqlalchemy as sa

revision = "20261123_18"
down_revision = "20261123_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "network_intent_profiles",
        sa.Column("profile_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("topology_profile_id", sa.String(), sa.ForeignKey("topology_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("scope_type", sa.String(12), nullable=False),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("scope_type IN ('PROJECT','LAB')", name="ck_network_intent_profiles_scope"),
        sa.CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_network_intent_profiles_status"),
        sa.CheckConstraint("(scope_type='PROJECT' AND scope_id=project_id AND lab_id IS NULL) OR (scope_type='LAB' AND scope_id=lab_id AND lab_id IS NOT NULL)", name="ck_network_intent_profiles_scope_id"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="ck_network_intent_profiles_name"),
        sa.UniqueConstraint("topology_profile_id", "name", name="uq_network_intent_profile_topology_name"),
    )
    op.create_index(
        "idx_network_intent_profiles_project_scope",
        "network_intent_profiles",
        ["project_id", "scope_type", "scope_id"],
    )
    op.create_index(
        "idx_network_intent_profiles_topology",
        "network_intent_profiles",
        ["topology_profile_id", "status"],
    )

    op.create_table(
        "network_intent_revisions",
        sa.Column("revision_id", sa.String(32), primary_key=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("network_intent_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("topology_revision_id", sa.String(), sa.ForeignKey("topology_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("topology_content_sha256", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("intent_sha256", sa.String(64), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("parent_revision_id", sa.String(), sa.ForeignKey("network_intent_revisions.revision_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("published_at", sa.String(), nullable=True),
        sa.Column("published_by", sa.String(128), nullable=True),
        sa.CheckConstraint("revision_number > 0", name="ck_network_intent_revisions_number"),
        sa.CheckConstraint("status IN ('DRAFT','PUBLISHED')", name="ck_network_intent_revisions_status"),
        sa.CheckConstraint("schema_version = '1.0'", name="ck_network_intent_revisions_schema_version"),
        sa.CheckConstraint("length(topology_content_sha256)=64 AND topology_content_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_network_intent_revisions_topology_hash"),
        sa.CheckConstraint("length(intent_sha256)=64 AND intent_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_network_intent_revisions_hash"),
        sa.CheckConstraint("length(definition_json) BETWEEN 2 AND 1000000", name="ck_network_intent_revisions_definition_size"),
        sa.UniqueConstraint("profile_id", "revision_number", name="uq_network_intent_revision_number"),
    )
    op.create_index(
        "idx_network_intent_revisions_profile_number",
        "network_intent_revisions",
        ["profile_id", "revision_number"],
    )
    op.create_index(
        "idx_network_intent_revisions_topology",
        "network_intent_revisions",
        ["topology_revision_id", "status"],
    )

    op.create_table(
        "device_capability_reports",
        sa.Column("report_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("device_id", sa.String(), sa.ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider_id", sa.String(32), nullable=True),
        sa.Column("platform", sa.String(120), nullable=False),
        sa.Column("software_version", sa.String(80), nullable=False),
        sa.Column("adapter_name", sa.String(80), nullable=False),
        sa.Column("adapter_version", sa.String(80), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False),
        sa.Column("capability_sha256", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.Column("recorded_by", sa.String(128), nullable=False),
        sa.CheckConstraint("source_type IN ('PROVIDER_ADAPTER','DEVICE_DISCOVERY')", name="ck_device_capability_reports_source"),
        sa.CheckConstraint("provider_id IS NULL OR provider_id IN ('gns3','cml','eve-ng','linux-native','openwrt')", name="ck_device_capability_reports_provider"),
        sa.CheckConstraint("length(trim(platform)) BETWEEN 1 AND 120", name="ck_device_capability_reports_platform"),
        sa.CheckConstraint("length(trim(software_version)) BETWEEN 1 AND 80", name="ck_device_capability_reports_version"),
        sa.CheckConstraint("length(capabilities_json) BETWEEN 2 AND 200000", name="ck_device_capability_reports_json_size"),
        sa.CheckConstraint("length(capability_sha256)=64 AND capability_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_device_capability_reports_hash"),
    )
    op.create_index(
        "idx_device_capability_reports_device_observed",
        "device_capability_reports",
        ["device_id", "observed_at"],
    )
    op.create_index(
        "idx_device_capability_reports_project_observed",
        "device_capability_reports",
        ["project_id", "observed_at"],
    )

    op.execute("""CREATE TRIGGER trg_network_intent_profiles_scope_insert
        BEFORE INSERT ON network_intent_profiles
        WHEN NOT EXISTS (
            SELECT 1 FROM topology_profiles t
            WHERE t.profile_id=NEW.topology_profile_id
              AND t.project_id=NEW.project_id
              AND t.scope_type=NEW.scope_type
              AND t.scope_id=NEW.scope_id
              AND COALESCE(t.lab_id,'')=COALESCE(NEW.lab_id,'')
              AND t.status='ACTIVE'
        )
        BEGIN SELECT RAISE(ABORT, 'network intent profile topology scope mismatch'); END""")
    op.execute("""CREATE TRIGGER trg_network_intent_profiles_no_delete
        BEFORE DELETE ON network_intent_profiles
        BEGIN SELECT RAISE(ABORT, 'network intent profiles must be archived, not deleted'); END""")
    op.execute("""CREATE TRIGGER trg_network_intent_profiles_identity_immutable
        BEFORE UPDATE OF profile_id,project_id,topology_profile_id,scope_type,scope_id,lab_id,created_at,created_by
        ON network_intent_profiles
        BEGIN SELECT RAISE(ABORT, 'network intent profile ownership and identity are immutable'); END""")
    op.execute("""CREATE TRIGGER trg_network_intent_revisions_scope_insert
        BEFORE INSERT ON network_intent_revisions
        WHEN NOT EXISTS (
            SELECT 1
            FROM network_intent_profiles p
            JOIN topology_revisions t ON t.profile_id=p.topology_profile_id
            WHERE p.profile_id=NEW.profile_id
              AND t.revision_id=NEW.topology_revision_id
              AND t.content_sha256=NEW.topology_content_sha256
              AND p.status='ACTIVE'
        )
        OR (
            NEW.parent_revision_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM network_intent_revisions parent
                WHERE parent.revision_id=NEW.parent_revision_id
                  AND parent.profile_id=NEW.profile_id
            )
        )
        BEGIN SELECT RAISE(ABORT, 'network intent revision topology or parent binding mismatch'); END""")
    op.execute("""CREATE TRIGGER trg_network_intent_revisions_immutable
        BEFORE UPDATE OF revision_id,profile_id,topology_revision_id,topology_content_sha256,
          schema_version,revision_number,definition_json,intent_sha256,provenance_json,
          parent_revision_id,created_at,created_by
        ON network_intent_revisions
        BEGIN SELECT RAISE(ABORT, 'network intent revision content is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_network_intent_revisions_published_immutable
        BEFORE UPDATE ON network_intent_revisions
        WHEN OLD.status='PUBLISHED'
        BEGIN SELECT RAISE(ABORT, 'published network intent revisions are immutable'); END""")
    op.execute("""CREATE TRIGGER trg_network_intent_revisions_no_delete
        BEFORE DELETE ON network_intent_revisions
        BEGIN SELECT RAISE(ABORT, 'network intent revision history cannot be deleted'); END""")
    op.execute("""CREATE TRIGGER trg_device_capability_reports_scope_insert
        BEFORE INSERT ON device_capability_reports
        WHEN NOT EXISTS (
            SELECT 1 FROM devices d
            WHERE d.device_id=NEW.device_id
              AND d.project_id=NEW.project_id
              AND d.status='ACTIVE'
        )
        BEGIN SELECT RAISE(ABORT, 'device capability report Project/Device scope mismatch'); END""")
    op.execute("""CREATE TRIGGER trg_device_capability_reports_immutable
        BEFORE UPDATE ON device_capability_reports
        BEGIN SELECT RAISE(ABORT, 'device capability observations are immutable'); END""")
    op.execute("""CREATE TRIGGER trg_device_capability_reports_no_delete
        BEFORE DELETE ON device_capability_reports
        BEGIN SELECT RAISE(ABORT, 'device capability observation history cannot be deleted'); END""")

    bind = op.get_bind()
    permissions = (
        ("network_intent.read", "network_intent", "read", "View canonical vendor-neutral network intent and capability observations"),
        ("network_intent.manage", "network_intent", "manage", "Create and revise canonical network intent"),
        ("network_intent.publish", "network_intent", "publish", "Publish validated network intent revisions"),
    )
    for code, resource, action, description in permissions:
        bind.execute(
            sa.text("INSERT OR IGNORE INTO permissions(code,resource,action,description) VALUES(:code,:resource,:action,:description)"),
            {"code": code, "resource": resource, "action": action, "description": description},
        )
    grants = {
        "VIEWER": ("network_intent.read",),
        "OPERATOR": ("network_intent.read",),
        "ADMIN": ("network_intent.read", "network_intent.manage", "network_intent.publish"),
        "OWNER": ("network_intent.read", "network_intent.manage", "network_intent.publish"),
    }
    for scope in ("GLOBAL", "PROJECT"):
        for role_name, codes in grants.items():
            for permission in codes:
                bind.execute(
                    sa.text("INSERT OR IGNORE INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                    {"role": f"{scope.lower()}_{role_name.lower()}", "permission": permission},
                )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','28') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261123_18') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Network intent revisions and device capability observations are audit-bearing; "
        "restore a verified pre-migration SQLite backup instead."
    )
