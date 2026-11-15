"""Add immutable Project/Lab topology profiles and revisions.
Revision ID: 20261115_12
Revises: 20261115_11
"""
from alembic import op
import sqlalchemy as sa

revision = "20261115_12"
down_revision = "20261115_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topology_profiles",
        sa.Column("profile_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False),
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
        sa.CheckConstraint("scope_type IN ('PROJECT','LAB')", name="ck_topology_profiles_scope"),
        sa.CheckConstraint("status IN ('ACTIVE','ARCHIVED')", name="ck_topology_profiles_status"),
        sa.CheckConstraint("(scope_type='PROJECT' AND scope_id=project_id AND lab_id IS NULL) OR (scope_type='LAB' AND scope_id=lab_id AND lab_id IS NOT NULL)", name="ck_topology_profiles_scope_id"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="ck_topology_profiles_name"),
        sa.UniqueConstraint("project_id", "scope_type", "scope_id", "name", name="uq_topology_profile_name"),
    )
    op.create_index("idx_topology_profiles_project_scope", "topology_profiles", ["project_id", "scope_type", "scope_id"])
    op.create_table(
        "topology_revisions",
        sa.Column("revision_id", sa.String(), primary_key=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("topology_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("definition_json", sa.String(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("published_at", sa.String(), nullable=True),
        sa.Column("published_by", sa.String(128), nullable=True),
        sa.CheckConstraint("revision_number > 0", name="ck_topology_revisions_number"),
        sa.CheckConstraint("status IN ('DRAFT','PUBLISHED')", name="ck_topology_revisions_status"),
        sa.UniqueConstraint("profile_id", "revision_number", name="uq_topology_revision_number"),
    )
    op.create_index("idx_topology_revisions_profile_number", "topology_revisions", ["profile_id", "revision_number"])
    op.execute("""CREATE TRIGGER trg_topology_profiles_no_delete BEFORE DELETE ON topology_profiles BEGIN SELECT RAISE(ABORT, 'topology profiles must be archived, not deleted'); END""")
    op.execute("""CREATE TRIGGER trg_topology_revisions_immutable BEFORE UPDATE OF revision_id,profile_id,revision_number,definition_json,content_sha256,created_at,created_by ON topology_revisions BEGIN SELECT RAISE(ABORT, 'topology revision content is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_topology_revisions_no_delete BEFORE DELETE ON topology_revisions BEGIN SELECT RAISE(ABORT, 'topology revision history cannot be deleted'); END""")
    bind = op.get_bind()
    permissions = (
        ("topology.read", "topology", "read", "View canonical topology profiles and revisions"),
        ("topology.manage", "topology", "manage", "Create topology profiles and draft revisions"),
        ("topology.publish", "topology", "publish", "Publish immutable topology revisions"),
    )
    for code, resource, action, description in permissions:
        bind.execute(sa.text("INSERT OR IGNORE INTO permissions(code,resource,action,description) VALUES(:code,:resource,:action,:description)"),
                     {"code": code, "resource": resource, "action": action, "description": description})
    grants = {
        "VIEWER": ("topology.read",), "OPERATOR": ("topology.read",),
        "ADMIN": ("topology.read", "topology.manage", "topology.publish"),
        "OWNER": ("topology.read", "topology.manage", "topology.publish"),
    }
    for scope in ("GLOBAL", "PROJECT"):
        for role_name, codes in grants.items():
            for permission in codes:
                bind.execute(sa.text("INSERT OR IGNORE INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                             {"role": f"{scope.lower()}_{role_name.lower()}", "permission": permission})
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('version','21') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    bind.exec_driver_sql("INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261115_12') ON CONFLICT(key) DO UPDATE SET value=excluded.value")


def downgrade() -> None:
    raise RuntimeError("Topology profiles and revision history are audit-bearing; restore a verified pre-migration SQLite backup instead.")
