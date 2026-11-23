"""Persist immutable Packet Tracer native sources beside canonical topology revisions.

Revision ID: 20261123_17
Revises: 20261122_16
"""
from alembic import op
import sqlalchemy as sa

revision = "20261123_17"
down_revision = "20261122_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topology_native_sources",
        sa.Column("source_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("topology_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_id", sa.String(), sa.ForeignKey("topology_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("format", sa.String(64), nullable=False),
        sa.Column("format_version", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("source_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("codec_name", sa.String(64), nullable=False),
        sa.Column("codec_version", sa.String(32), nullable=False),
        sa.Column("mapping_json", sa.Text(), nullable=False),
        sa.Column("compatibility_report_json", sa.Text(), nullable=False),
        sa.Column("imported_at", sa.String(), nullable=False),
        sa.Column("imported_by", sa.String(128), nullable=False),
        sa.CheckConstraint("format = 'CISCO_PACKET_TRACER_PKT'", name="ck_topology_native_sources_format"),
        sa.CheckConstraint("length(trim(filename)) BETWEEN 1 AND 255", name="ck_topology_native_sources_filename"),
        sa.CheckConstraint("length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_topology_native_sources_sha256"),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 3500000", name="ck_topology_native_sources_size"),
        sa.CheckConstraint("length(source_bytes) = size_bytes", name="ck_topology_native_sources_bytes"),
        sa.CheckConstraint("length(trim(format_version)) BETWEEN 1 AND 32", name="ck_topology_native_sources_version"),
        sa.CheckConstraint("length(trim(codec_name)) BETWEEN 1 AND 64", name="ck_topology_native_sources_codec"),
    )
    op.create_index(
        "idx_topology_native_sources_profile_imported",
        "topology_native_sources",
        ["profile_id", "imported_at"],
    )
    op.create_index(
        "idx_topology_native_sources_revision",
        "topology_native_sources",
        ["revision_id"],
    )
    op.execute("""CREATE TRIGGER trg_topology_native_sources_scope_insert
        BEFORE INSERT ON topology_native_sources
        WHEN NOT EXISTS (
            SELECT 1
            FROM topology_profiles p
            JOIN topology_revisions r ON r.profile_id = p.profile_id
            WHERE p.profile_id = NEW.profile_id
              AND p.project_id = NEW.project_id
              AND r.revision_id = NEW.revision_id
              AND r.profile_id = NEW.profile_id
        )
        BEGIN SELECT RAISE(ABORT, 'native source Project/profile/revision scope is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_topology_native_sources_immutable
        BEFORE UPDATE ON topology_native_sources
        BEGIN SELECT RAISE(ABORT, 'native topology source provenance is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_topology_native_sources_no_delete
        BEFORE DELETE ON topology_native_sources
        BEGIN SELECT RAISE(ABORT, 'native topology source provenance cannot be deleted'); END""")
    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','27') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261123_17') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Native topology source provenance is audit-bearing; restore a verified pre-migration SQLite backup instead."
    )
