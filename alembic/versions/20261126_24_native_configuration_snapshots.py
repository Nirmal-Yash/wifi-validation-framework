"""Add immutable, version-bound native vendor configuration snapshots.
Revision ID: 20261126_24
Revises: 20261124_23
"""
from alembic import op
import sqlalchemy as sa
revision = "20261126_24"
down_revision = "20261124_23"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "native_configuration_snapshots",
        sa.Column("snapshot_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(128), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_id", sa.String(32), sa.ForeignKey("topology_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("topology_revision_id", sa.String(32), sa.ForeignKey("topology_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("topology_content_sha256", sa.String(64), nullable=False),
        sa.Column("logical_node_id", sa.String(64), nullable=False),
        sa.Column("device_id", sa.String(32), sa.ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("capability_report_id", sa.String(32), sa.ForeignKey("device_capability_reports.report_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("capability_sha256", sa.String(64), nullable=False),
        sa.Column("adapter_id", sa.String(32), nullable=False),
        sa.Column("adapter_version", sa.String(80), nullable=False),
        sa.Column("platform", sa.String(120), nullable=False),
        sa.Column("software_version", sa.String(80), nullable=False),
        sa.Column("configuration_kind", sa.String(24), nullable=False),
        sa.Column("format_id", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.CheckConstraint("length(topology_content_sha256)=64 AND topology_content_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_native_config_topology_hash"),
        sa.CheckConstraint("length(capability_sha256)=64 AND capability_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_native_config_capability_hash"),
        sa.CheckConstraint("length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_native_config_content_hash"),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 2097152 AND length(content_bytes)=size_bytes", name="ck_native_config_content_size"),
        sa.CheckConstraint("configuration_kind IN ('NATIVE_SOURCE','CANDIDATE_CONFIG')", name="ck_native_config_kind"),
        sa.CheckConstraint("format_id IN ('FRR_CONF','LINUX_NETWORKD','NFTABLES','IOS_XE_CLI','EOS_CLI','JUNOS_SET','PANOS_SET')", name="ck_native_config_format"),
        sa.CheckConstraint("length(trim(logical_node_id)) BETWEEN 1 AND 64", name="ck_native_config_node"),
        sa.CheckConstraint("length(trim(adapter_id)) BETWEEN 1 AND 32", name="ck_native_config_adapter"),
        sa.CheckConstraint("length(trim(adapter_version)) BETWEEN 1 AND 80", name="ck_native_config_adapter_version"),
        sa.CheckConstraint("length(trim(platform)) BETWEEN 1 AND 120", name="ck_native_config_platform"),
        sa.CheckConstraint("length(trim(software_version)) BETWEEN 1 AND 80", name="ck_native_config_software_version"),
        sa.CheckConstraint("length(trim(filename)) BETWEEN 1 AND 255 AND instr(filename,'/')=0 AND instr(filename,char(92))=0", name="ck_native_config_filename"),
        sa.CheckConstraint("length(metadata_json) BETWEEN 2 AND 16384", name="ck_native_config_metadata"),
        sa.CheckConstraint("length(trim(created_by)) BETWEEN 1 AND 128", name="ck_native_config_actor"),
    )
    op.create_index("idx_native_config_profile_revision","native_configuration_snapshots",["profile_id","topology_revision_id","created_at"])
    op.create_index("idx_native_config_device_created","native_configuration_snapshots",["device_id","created_at"])
    op.create_index("idx_native_config_capability_report","native_configuration_snapshots",["capability_report_id"])
    op.execute("""CREATE TRIGGER trg_native_config_scope_insert BEFORE INSERT ON native_configuration_snapshots
      WHEN NOT EXISTS (
        SELECT 1 FROM topology_profiles p
        JOIN topology_revisions r ON r.profile_id=p.profile_id
        JOIN devices d ON d.device_id=NEW.device_id
        JOIN labs l ON l.lab_id=d.lab_id AND l.project_id=d.project_id
        JOIN device_capability_reports c ON c.report_id=NEW.capability_report_id
          AND c.device_id=d.device_id AND c.project_id=d.project_id
        WHERE p.profile_id=NEW.profile_id AND p.project_id=NEW.project_id AND p.status='ACTIVE'
          AND r.revision_id=NEW.topology_revision_id AND r.content_sha256=NEW.topology_content_sha256 AND r.status='PUBLISHED'
          AND d.project_id=NEW.project_id AND d.status='ACTIVE' AND l.status='ACTIVE'
          AND c.capability_sha256=NEW.capability_sha256 AND c.platform=NEW.platform AND c.software_version=NEW.software_version
          AND ((p.scope_type='PROJECT' AND p.lab_id IS NULL) OR (p.scope_type='LAB' AND p.lab_id=d.lab_id))
          AND EXISTS (SELECT 1 FROM json_each(r.definition_json,'$.nodes') node WHERE json_extract(node.value,'$.id')=NEW.logical_node_id)
      )
      BEGIN SELECT RAISE(ABORT,'native configuration scope, topology, Device or capability binding mismatch'); END""")
    op.execute("""CREATE TRIGGER trg_native_config_immutable BEFORE UPDATE ON native_configuration_snapshots
      BEGIN SELECT RAISE(ABORT,'native configuration snapshots are immutable'); END""")
    op.execute("""CREATE TRIGGER trg_native_config_no_delete BEFORE DELETE ON native_configuration_snapshots
      BEGIN SELECT RAISE(ABORT,'native configuration snapshot history cannot be deleted'); END""")
    bind=op.get_bind()
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('version','34') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261126_24') ON CONFLICT(key) DO UPDATE SET value=excluded.value")

def downgrade() -> None:
    raise RuntimeError("Native configuration snapshots are immutable; restore a verified pre-migration backup instead.")
