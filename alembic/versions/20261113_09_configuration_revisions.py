"""Add versioned configuration profiles, revisions and assignments.

Revision ID: 20261113_09
Revises: 20261113_08
"""
from alembic import op
import sqlalchemy as sa

revision = "20261113_09"
down_revision = "20261113_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "configuration_profiles",
        sa.Column("profile_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("scope_type", sa.String(), nullable=False),
        sa.Column("scope_id", sa.String(), nullable=False),
        sa.Column("schema_record_id", sa.String(), sa.ForeignKey("configuration_schemas.schema_record_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.CheckConstraint("scope_type IN ('PROJECT','LAB','DEVICE')", name="ck_configuration_profiles_scope"),
        sa.CheckConstraint("status IN ('DRAFT','PUBLISHED','ARCHIVED')", name="ck_configuration_profiles_status"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="ck_configuration_profiles_name"),
        sa.UniqueConstraint("project_id","scope_type","scope_id","name",name="uq_configuration_profile_name"),
    )
    op.create_index(
        "idx_configuration_profiles_project_scope",
        "configuration_profiles",
        ["project_id","scope_type","scope_id"],
    )
    op.create_table(
        "configuration_revisions",
        sa.Column("revision_id", sa.String(), primary_key=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("configuration_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("schema_record_id", sa.String(), sa.ForeignKey("configuration_schemas.schema_record_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("values_json", sa.String(), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("provenance_json", sa.String(), nullable=False),
        sa.Column("parent_revision_id", sa.String(), sa.ForeignKey("configuration_revisions.revision_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("published_at", sa.String(), nullable=True),
        sa.Column("published_by", sa.String(), nullable=True),
        sa.CheckConstraint("revision_number > 0", name="ck_configuration_revisions_number"),
        sa.CheckConstraint("status IN ('DRAFT','PUBLISHED')", name="ck_configuration_revisions_status"),
        sa.UniqueConstraint("profile_id","revision_number",name="uq_configuration_revision_number"),
    )
    op.create_index(
        "idx_configuration_revisions_profile_number",
        "configuration_revisions",
        ["profile_id","revision_number"],
    )
    op.execute(
        """CREATE TRIGGER trg_configuration_revisions_immutable
           BEFORE UPDATE OF revision_id,profile_id,schema_record_id,revision_number,
             values_json,configuration_hash,provenance_json,parent_revision_id,created_at,created_by
           ON configuration_revisions
           BEGIN SELECT RAISE(ABORT, 'configuration revision content is immutable'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_configuration_revisions_no_delete
           BEFORE DELETE ON configuration_revisions
           BEGIN SELECT RAISE(ABORT, 'configuration revision history cannot be deleted'); END"""
    )
    op.create_table(
        "configuration_assignments",
        sa.Column("assignment_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("configuration_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_id", sa.String(), sa.ForeignKey("configuration_revisions.revision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assigned_at", sa.String(), nullable=False),
        sa.Column("assigned_by", sa.String(), nullable=False),
        sa.CheckConstraint("target_type IN ('PROJECT','LAB','DEVICE')", name="ck_configuration_assignments_target"),
        sa.UniqueConstraint("project_id","target_type","target_id",name="uq_configuration_assignment_target"),
    )
    op.create_index(
        "idx_configuration_assignments_target",
        "configuration_assignments",
        ["project_id","target_type","target_id"],
    )
    op.execute(
        """CREATE TRIGGER trg_configuration_assignments_no_delete
           BEFORE DELETE ON configuration_assignments
           BEGIN SELECT RAISE(ABORT, 'configuration assignments must be replaced, not deleted'); END"""
    )
    bind=op.get_bind()
    for code,resource,action,description in (
        ("configurations.read","configurations","read","View configuration profiles, revisions and assignments"),
        ("configurations.manage","configurations","manage","Create configuration profiles and revisions"),
        ("configurations.publish","configurations","publish","Publish revisions and assign configuration"),
    ):
        # P12 seeded these permission records; P13 only adds them to the applicable built-in roles.
        grants={
            "VIEWER":("configurations.read",),
            "OPERATOR":("configurations.read",),
            "ADMIN":("configurations.read","configurations.manage","configurations.publish"),
            "OWNER":("configurations.read","configurations.manage","configurations.publish"),
        }
        for scope in ("GLOBAL","PROJECT"):
            for role_name,codes in grants.items():
                for permission in codes:
                    bind.execute(
                        sa.text("INSERT OR IGNORE INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                        {"role":f"{scope.lower()}_{role_name.lower()}","permission":permission},
                    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES ('version','18') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES ('alembic_revision','20261113_09') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Configuration revisions and assignment history must not be destructively downgraded. "
        "Restore a verified pre-migration SQLite backup instead."
    )
