"""Persist hash-verified, immutable native topology reconciliation snapshots.

Revision ID: 20261126_25
Revises: 20261126_24
"""
from alembic import op
import sqlalchemy as sa

revision = "20261126_25"
down_revision = "20261126_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "native_topology_reconciliations",
        sa.Column("reconciliation_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(128), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_id", sa.String(32), sa.ForeignKey("topology_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("topology_revision_id", sa.String(32), sa.ForeignKey("topology_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("presentation_id", sa.String(32), sa.ForeignKey("topology_presentation_revisions.presentation_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("topology_source_artifacts.source_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reconciliation_sha256", sa.String(64), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.CheckConstraint(
            "status IN ('CLEAN','DRIFT_DETECTED','INCOMPLETE','RECONCILIATION_REQUIRED')",
            name="ck_native_topology_reconciliations_status",
        ),
        sa.CheckConstraint(
            "length(reconciliation_sha256)=64 AND reconciliation_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_native_topology_reconciliations_hash",
        ),
        sa.CheckConstraint(
            "length(details_json) BETWEEN 2 AND 4194304",
            name="ck_native_topology_reconciliations_details_size",
        ),
        sa.CheckConstraint(
            "length(trim(created_by)) BETWEEN 1 AND 128",
            name="ck_native_topology_reconciliations_actor",
        ),
    )
    op.create_index(
        "idx_native_topology_reconciliations_profile_created",
        "native_topology_reconciliations", ["profile_id", "created_at", "reconciliation_id"],
    )
    op.create_index(
        "idx_native_topology_reconciliations_revision_created",
        "native_topology_reconciliations", ["topology_revision_id", "created_at"],
    )
    op.create_index(
        "idx_native_topology_reconciliations_project_created",
        "native_topology_reconciliations", ["project_id", "created_at"],
    )

    op.execute("""CREATE TRIGGER trg_native_topology_reconciliations_scope_insert
        BEFORE INSERT ON native_topology_reconciliations
        WHEN NOT EXISTS (
            SELECT 1
            FROM topology_profiles p
            JOIN topology_revisions r
              ON r.profile_id=p.profile_id
            JOIN topology_presentation_revisions pr
              ON pr.profile_id=p.profile_id
             AND pr.topology_revision_id=r.revision_id
            JOIN topology_source_artifacts s
              ON s.profile_id=p.profile_id
             AND s.topology_revision_id=r.revision_id
            WHERE p.profile_id=NEW.profile_id
              AND p.project_id=NEW.project_id
              AND p.status='ACTIVE'
              AND r.revision_id=NEW.topology_revision_id
              AND pr.presentation_id=NEW.presentation_id
              AND pr.project_id=NEW.project_id
              AND pr.source_artifact_id=NEW.source_id
              AND s.source_id=NEW.source_id
              AND s.project_id=NEW.project_id
              AND s.topology_content_sha256=r.content_sha256
              AND pr.topology_content_sha256=r.content_sha256
        )
        BEGIN SELECT RAISE(ABORT, 'native topology reconciliation must bind one exact Project/Profile/Revision/Presentation/Source'); END""")
    op.execute("""CREATE TRIGGER trg_native_topology_reconciliations_immutable
        BEFORE UPDATE ON native_topology_reconciliations
        BEGIN SELECT RAISE(ABORT, 'native topology reconciliation evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_native_topology_reconciliations_no_delete
        BEFORE DELETE ON native_topology_reconciliations
        BEGIN SELECT RAISE(ABORT, 'native topology reconciliation history cannot be deleted'); END""")

    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','35') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261126_25') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Native topology reconciliation history is immutable audit evidence; "
        "restore a verified pre-migration backup instead."
    )
