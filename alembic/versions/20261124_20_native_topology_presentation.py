"""Add immutable native topology presentation and generic source provenance.

Revision ID: 20261124_20
Revises: 20261124_19
"""
from alembic import op
import sqlalchemy as sa

revision = "20261124_20"
down_revision = "20261124_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topology_source_artifacts",
        sa.Column("source_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("topology_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("topology_revision_id", sa.String(), sa.ForeignKey("topology_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("topology_content_sha256", sa.String(64), nullable=False),
        sa.Column("format_id", sa.String(64), nullable=False),
        sa.Column("format_version", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("source_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("codec_name", sa.String(64), nullable=False),
        sa.Column("codec_version", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("imported_at", sa.String(), nullable=False),
        sa.Column("imported_by", sa.String(128), nullable=False),
        sa.CheckConstraint("length(trim(format_id)) BETWEEN 2 AND 64", name="ck_topology_source_artifacts_format"),
        sa.CheckConstraint("length(trim(format_version)) BETWEEN 1 AND 32", name="ck_topology_source_artifacts_format_version"),
        sa.CheckConstraint("length(trim(filename)) BETWEEN 1 AND 255 AND instr(filename,'/')=0 AND instr(filename,char(92))=0", name="ck_topology_source_artifacts_filename"),
        sa.CheckConstraint("length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_topology_source_artifacts_sha256"),
        sa.CheckConstraint("length(topology_content_sha256)=64 AND topology_content_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_topology_source_artifacts_topology_hash"),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 52428800 AND length(source_bytes)=size_bytes", name="ck_topology_source_artifacts_bytes"),
        sa.CheckConstraint("length(metadata_json) BETWEEN 2 AND 500000", name="ck_topology_source_artifacts_metadata"),
        sa.CheckConstraint("length(trim(codec_name)) BETWEEN 1 AND 64", name="ck_topology_source_artifacts_codec"),
        sa.CheckConstraint("length(trim(codec_version)) BETWEEN 1 AND 64", name="ck_topology_source_artifacts_codec_version"),
    )
    op.create_index("idx_topology_source_artifacts_profile_imported", "topology_source_artifacts", ["profile_id", "imported_at"])
    op.create_index("idx_topology_source_artifacts_revision", "topology_source_artifacts", ["topology_revision_id"])
    op.execute("""CREATE TRIGGER trg_topology_source_artifacts_scope_insert
        BEFORE INSERT ON topology_source_artifacts
        WHEN NOT EXISTS (
            SELECT 1 FROM topology_profiles p
            JOIN topology_revisions r ON r.profile_id=p.profile_id
            WHERE p.profile_id=NEW.profile_id AND p.project_id=NEW.project_id
              AND r.revision_id=NEW.topology_revision_id
              AND r.content_sha256=NEW.topology_content_sha256
        )
        BEGIN SELECT RAISE(ABORT, 'native source Project/profile/revision/hash scope is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_topology_source_artifacts_immutable
        BEFORE UPDATE ON topology_source_artifacts
        BEGIN SELECT RAISE(ABORT, 'native source artifact provenance is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_topology_source_artifacts_no_delete
        BEFORE DELETE ON topology_source_artifacts
        BEGIN SELECT RAISE(ABORT, 'native source artifact history cannot be deleted'); END""")

    op.create_table(
        "topology_source_assets",
        sa.Column("asset_id", sa.String(32), primary_key=True),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("topology_source_artifacts.source_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint("length(trim(relative_path)) BETWEEN 1 AND 512 AND substr(relative_path,1,1)<>'/' AND instr(relative_path,char(92))=0 AND instr(relative_path,'//')=0 AND instr('/'||relative_path||'/','/../')=0 AND instr('/'||relative_path||'/','/./')=0", name="ck_topology_source_assets_path"),
        sa.CheckConstraint("length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_topology_source_assets_sha256"),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 20971520 AND length(content_bytes)=size_bytes", name="ck_topology_source_assets_bytes"),
        sa.CheckConstraint("length(media_type)<=128", name="ck_topology_source_assets_media_type"),
        sa.UniqueConstraint("source_id", "relative_path", name="uq_topology_source_asset_path"),
    )
    op.create_index("idx_topology_source_assets_source", "topology_source_assets", ["source_id"])
    op.execute("""CREATE TRIGGER trg_topology_source_assets_immutable
        BEFORE UPDATE ON topology_source_assets
        BEGIN SELECT RAISE(ABORT, 'native source asset content is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_topology_source_assets_no_delete
        BEFORE DELETE ON topology_source_assets
        BEGIN SELECT RAISE(ABORT, 'native source asset history cannot be deleted'); END""")

    op.create_table(
        "topology_presentation_revisions",
        sa.Column("presentation_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("topology_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("topology_revision_id", sa.String(), sa.ForeignKey("topology_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("topology_content_sha256", sa.String(64), nullable=False),
        sa.Column("presentation_json", sa.Text(), nullable=False),
        sa.Column("presentation_sha256", sa.String(64), nullable=False),
        sa.Column("source_artifact_id", sa.String(32), sa.ForeignKey("topology_source_artifacts.source_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("published_at", sa.String(), nullable=True),
        sa.Column("published_by", sa.String(128), nullable=True),
        sa.CheckConstraint("revision_number > 0", name="ck_topology_presentation_revision_number"),
        sa.CheckConstraint("schema_version = '1.0'", name="ck_topology_presentation_schema_version"),
        sa.CheckConstraint("status IN ('DRAFT','PUBLISHED')", name="ck_topology_presentation_status"),
        sa.CheckConstraint("length(topology_content_sha256)=64 AND topology_content_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_topology_presentation_topology_hash"),
        sa.CheckConstraint("length(presentation_sha256)=64 AND presentation_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_topology_presentation_hash"),
        sa.CheckConstraint("length(presentation_json) BETWEEN 2 AND 1000000", name="ck_topology_presentation_json_size"),
        sa.UniqueConstraint("topology_revision_id", "revision_number", name="uq_topology_presentation_revision_number"),
    )
    op.create_index("idx_topology_presentation_profile_revision", "topology_presentation_revisions", ["profile_id", "topology_revision_id", "revision_number"])
    op.create_index("idx_topology_presentation_topology_revision", "topology_presentation_revisions", ["topology_revision_id", "status"])
    op.create_index("idx_topology_presentation_source", "topology_presentation_revisions", ["source_artifact_id"])
    op.execute("""CREATE TRIGGER trg_topology_presentation_scope_insert
        BEFORE INSERT ON topology_presentation_revisions
        WHEN NOT EXISTS (
            SELECT 1 FROM topology_profiles p
            JOIN topology_revisions r ON r.profile_id=p.profile_id
            WHERE p.profile_id=NEW.profile_id AND p.project_id=NEW.project_id
              AND r.revision_id=NEW.topology_revision_id
              AND r.content_sha256=NEW.topology_content_sha256
        )
        OR (
            NEW.source_artifact_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM topology_source_artifacts s
                WHERE s.source_id=NEW.source_artifact_id
                  AND s.project_id=NEW.project_id AND s.profile_id=NEW.profile_id
                  AND s.topology_revision_id=NEW.topology_revision_id
            )
        )
        BEGIN SELECT RAISE(ABORT, 'presentation Project/profile/topology/source scope is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_topology_presentation_identity_immutable
        BEFORE UPDATE OF presentation_id,project_id,profile_id,topology_revision_id,revision_number,
            schema_version,topology_content_sha256,presentation_json,presentation_sha256,
            source_artifact_id,created_at,created_by
        ON topology_presentation_revisions
        BEGIN SELECT RAISE(ABORT, 'topology presentation revision content is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_topology_presentation_state_transition
        BEFORE UPDATE OF status ON topology_presentation_revisions
        WHEN NOT (OLD.status='DRAFT' AND NEW.status='PUBLISHED')
        BEGIN SELECT RAISE(ABORT, 'topology presentation state transition is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_topology_presentation_publish_scope
        BEFORE UPDATE OF status ON topology_presentation_revisions
        WHEN NEW.status='PUBLISHED' AND NOT EXISTS (
            SELECT 1 FROM topology_revisions r
            WHERE r.revision_id=NEW.topology_revision_id AND r.profile_id=NEW.profile_id
              AND r.content_sha256=NEW.topology_content_sha256 AND r.status='PUBLISHED'
        )
        BEGIN SELECT RAISE(ABORT, 'presentation requires its pinned topology revision to be published'); END""")
    op.execute("""CREATE TRIGGER trg_topology_presentation_publish_metadata
        BEFORE UPDATE OF status ON topology_presentation_revisions
        WHEN NEW.status='PUBLISHED' AND (NEW.published_at IS NULL OR NEW.published_by IS NULL)
        BEGIN SELECT RAISE(ABORT, 'published presentation requires publisher and timestamp'); END""")
    op.execute("""CREATE TRIGGER trg_topology_presentation_published_immutable
        BEFORE UPDATE ON topology_presentation_revisions
        WHEN OLD.status='PUBLISHED'
        BEGIN SELECT RAISE(ABORT, 'published topology presentation revisions are immutable'); END""")
    op.execute("""CREATE TRIGGER trg_topology_presentation_no_delete
        BEFORE DELETE ON topology_presentation_revisions
        BEGIN SELECT RAISE(ABORT, 'topology presentation history cannot be deleted'); END""")

    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','30') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261124_20') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Native topology presentation and source provenance are audit-bearing; "
        "restore a verified pre-migration SQLite backup instead."
    )
