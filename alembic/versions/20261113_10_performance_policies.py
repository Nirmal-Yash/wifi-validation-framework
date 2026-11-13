"""Add Project/Lab-scoped versioned performance policy profiles.

Revision ID: 20261113_10
Revises: 20261113_09
"""
from alembic import op
import sqlalchemy as sa

revision = "20261113_10"
down_revision = "20261113_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "performance_policy_profiles",
        sa.Column("policy_profile_id",sa.String(),primary_key=True),
        sa.Column("project_id",sa.String(),sa.ForeignKey("projects.project_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("name",sa.String(),nullable=False),
        sa.Column("description",sa.String(),nullable=False,server_default=""),
        sa.Column("scope_type",sa.String(),nullable=False),
        sa.Column("scope_id",sa.String(),nullable=False),
        sa.Column("status",sa.String(),nullable=False,server_default="ACTIVE"),
        sa.Column("created_at",sa.String(),nullable=False),
        sa.Column("updated_at",sa.String(),nullable=False),
        sa.Column("created_by",sa.String(),nullable=False),
        sa.Column("updated_by",sa.String(),nullable=False),
        sa.CheckConstraint("scope_type IN ('PROJECT','LAB')",name="ck_performance_policy_profiles_scope"),
        sa.CheckConstraint("status IN ('ACTIVE','ARCHIVED')",name="ck_performance_policy_profiles_status"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 120",name="ck_performance_policy_profiles_name"),
        sa.UniqueConstraint("project_id","scope_type","scope_id","name",name="uq_performance_policy_profile_name"),
    )
    op.create_index(
        "idx_performance_policy_profiles_project_scope",
        "performance_policy_profiles",["project_id","scope_type","scope_id"],
    )
    op.create_table(
        "performance_policy_revisions",
        sa.Column("revision_id",sa.String(),primary_key=True),
        sa.Column("policy_profile_id",sa.String(),sa.ForeignKey("performance_policy_profiles.policy_profile_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("revision_number",sa.Integer(),nullable=False),
        sa.Column("policy_json",sa.String(),nullable=False),
        sa.Column("policy_hash",sa.String(64),nullable=False),
        sa.Column("status",sa.String(),nullable=False,server_default="DRAFT"),
        sa.Column("created_at",sa.String(),nullable=False),
        sa.Column("created_by",sa.String(),nullable=False),
        sa.Column("published_at",sa.String(),nullable=True),
        sa.Column("published_by",sa.String(),nullable=True),
        sa.CheckConstraint("revision_number > 0",name="ck_performance_policy_revisions_number"),
        sa.CheckConstraint("status IN ('DRAFT','PUBLISHED')",name="ck_performance_policy_revisions_status"),
        sa.UniqueConstraint("policy_profile_id","revision_number",name="uq_performance_policy_revision_number"),
    )
    op.create_index(
        "idx_performance_policy_revisions_profile_number",
        "performance_policy_revisions",["policy_profile_id","revision_number"],
    )
    op.execute(
        """CREATE TRIGGER trg_performance_policy_revisions_immutable
           BEFORE UPDATE OF revision_id,policy_profile_id,revision_number,policy_json,policy_hash,created_at,created_by
           ON performance_policy_revisions
           BEGIN SELECT RAISE(ABORT, 'performance policy revision content is immutable'); END"""
    )
    op.execute(
        """CREATE TRIGGER trg_performance_policy_revisions_no_delete
           BEFORE DELETE ON performance_policy_revisions
           BEGIN SELECT RAISE(ABORT, 'performance policy revision history cannot be deleted'); END"""
    )
    op.create_table(
        "performance_policy_assignments",
        sa.Column("assignment_id",sa.String(),primary_key=True),
        sa.Column("project_id",sa.String(),sa.ForeignKey("projects.project_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("lab_id",sa.String(),nullable=False),
        sa.Column("policy_profile_id",sa.String(),sa.ForeignKey("performance_policy_profiles.policy_profile_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("revision_id",sa.String(),sa.ForeignKey("performance_policy_revisions.revision_id",ondelete="RESTRICT"),nullable=False),
        sa.Column("assigned_at",sa.String(),nullable=False),
        sa.Column("assigned_by",sa.String(),nullable=False),
        sa.UniqueConstraint("project_id","lab_id",name="uq_performance_policy_assignment_lab"),
    )
    op.create_index(
        "idx_performance_policy_assignments_lab",
        "performance_policy_assignments",["project_id","lab_id"],
    )
    op.execute(
        """CREATE TRIGGER trg_performance_policy_assignments_no_delete
           BEFORE DELETE ON performance_policy_assignments
           BEGIN SELECT RAISE(ABORT, 'performance policy assignments must be replaced, not deleted'); END"""
    )
    bind=op.get_bind()
    for code,resource,action,description in (
        ("performance.read","performance","read","View performance policy profiles, revisions and evaluations"),
        ("performance.manage","performance","manage","Create performance policy profiles and revisions"),
        ("performance.publish","performance","publish","Publish and assign performance policy revisions"),
    ):
        bind.execute(
            sa.text("INSERT OR IGNORE INTO permissions(code,resource,action,description) VALUES(:code,:resource,:action,:description)"),
            {"code":code,"resource":resource,"action":action,"description":description},
        )
    grants={
        "VIEWER":("performance.read",),
        "OPERATOR":("performance.read",),
        "ADMIN":("performance.read","performance.manage","performance.publish"),
        "OWNER":("performance.read","performance.manage","performance.publish"),
    }
    for scope in ("GLOBAL","PROJECT"):
        for role_name,codes in grants.items():
            for permission in codes:
                bind.execute(
                    sa.text("INSERT OR IGNORE INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                    {"role":f"{scope.lower()}_{role_name.lower()}","permission":permission},
                )
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('version','19') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261113_10') ON CONFLICT(key) DO UPDATE SET value=excluded.value")


def downgrade() -> None:
    raise RuntimeError(
        "Performance policy and evaluation history must not be destructively downgraded. "
        "Restore a verified pre-migration SQLite backup instead."
    )
