"""Add topology-bound infrastructure resource lifecycle observations and recovery.

Revision ID: 20261124_22
Revises: 20261124_21
"""
from alembic import op
import sqlalchemy as sa

revision = "20261124_22"
down_revision = "20261124_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite parent key for exact profile/revision pairing.
    op.create_index(
        "uq_topology_revision_profile_revision",
        "topology_revisions", ["profile_id", "revision_id"], unique=True,
    )
    op.create_table(
        "infrastructure_resource_bindings",
        sa.Column("binding_id", sa.String(32), primary_key=True),
        sa.Column("workspace_id", sa.String(32), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=False),
        sa.Column("resource_address", sa.String(512), nullable=False),
        sa.Column("resource_type", sa.String(160), nullable=False),
        sa.Column("topology_profile_id", sa.String(), nullable=False),
        sa.Column("topology_revision_id", sa.String(), nullable=False),
        sa.Column("topology_node_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "superseded_by", sa.String(32),
            sa.ForeignKey("infrastructure_resource_bindings.binding_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "lab_id"],
            ["opentofu_workspaces.workspace_id", "opentofu_workspaces.project_id", "opentofu_workspaces.lab_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["topology_profile_id", "topology_revision_id"],
            ["topology_revisions.profile_id", "topology_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("length(trim(resource_address)) BETWEEN 1 AND 512", name="ck_infra_binding_address"),
        sa.CheckConstraint("length(trim(resource_type)) BETWEEN 1 AND 160", name="ck_infra_binding_type"),
        sa.CheckConstraint("length(trim(topology_node_id)) BETWEEN 1 AND 64", name="ck_infra_binding_node"),
        sa.CheckConstraint("status IN ('PENDING','ACTIVE','SUPERSEDED')", name="ck_infra_binding_status"),
        sa.CheckConstraint(
            "(status IN ('PENDING','ACTIVE') AND superseded_by IS NULL) OR (status='SUPERSEDED' AND superseded_by IS NOT NULL)",
            name="ck_infra_binding_supersession",
        ),
    )
    op.create_index(
        "uq_infra_resource_binding_active",
        "infrastructure_resource_bindings", ["workspace_id", "resource_address"],
        unique=True, sqlite_where=sa.text("status='ACTIVE'"),
    )
    op.create_index(
        "idx_infra_resource_bindings_workspace",
        "infrastructure_resource_bindings", ["workspace_id", "created_at"],
    )
    op.create_index(
        "idx_infra_resource_bindings_topology",
        "infrastructure_resource_bindings",
        ["topology_profile_id", "topology_revision_id", "topology_node_id"],
    )
    op.create_table(
        "infrastructure_reconciliations",
        sa.Column("reconciliation_id", sa.String(32), primary_key=True),
        sa.Column("workspace_id", sa.String(32), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("lab_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("state_sha256", sa.String(64), nullable=False),
        sa.Column("refresh_plan_sha256", sa.String(64), nullable=False),
        sa.Column("resource_count", sa.Integer(), nullable=False),
        sa.Column("drift_count", sa.Integer(), nullable=False),
        sa.Column("orphan_count", sa.Integer(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id", "lab_id"],
            ["opentofu_workspaces.workspace_id", "opentofu_workspaces.project_id", "opentofu_workspaces.lab_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('CLEAN','DRIFT_DETECTED','ORPHANED_RESOURCES','MISSING_RESOURCES','ORPHANED_AND_MISSING','DRIFT_ORPHAN_OR_MISSING')",
            name="ck_infra_reconcile_status",
        ),
        sa.CheckConstraint("length(state_sha256)=64 AND state_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_infra_reconcile_state_hash"),
        sa.CheckConstraint("length(refresh_plan_sha256)=64 AND refresh_plan_sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_infra_reconcile_plan_hash"),
        sa.CheckConstraint("resource_count >= 0 AND resource_count <= 100000", name="ck_infra_reconcile_resource_count"),
        sa.CheckConstraint("drift_count >= 0 AND drift_count <= 100000", name="ck_infra_reconcile_drift_count"),
        sa.CheckConstraint("orphan_count >= 0 AND orphan_count <= 100000", name="ck_infra_reconcile_orphan_count"),
        sa.CheckConstraint("missing_count >= 0 AND missing_count <= 100000", name="ck_infra_reconcile_missing_count"),
        sa.CheckConstraint("length(details_json) BETWEEN 2 AND 4194304", name="ck_infra_reconcile_details_size"),
    )
    op.create_index(
        "idx_infra_reconciliations_workspace_created",
        "infrastructure_reconciliations", ["workspace_id", "created_at"],
    )
    op.create_index(
        "idx_infra_reconciliations_project_created",
        "infrastructure_reconciliations", ["project_id", "created_at"],
    )
    op.add_column(
        "opentofu_plans",
        # SQLite supports adding a nullable scalar column in-place. Its
        # same-workspace reference is enforced by trg_opentofu_recovery_plan_scope_insert.
        sa.Column("reconciliation_id", sa.String(32), nullable=True),
    )
    op.create_index("idx_opentofu_plans_reconciliation", "opentofu_plans", ["reconciliation_id"])

    op.execute("""CREATE TRIGGER trg_infra_binding_scope_insert
        BEFORE INSERT ON infrastructure_resource_bindings
        WHEN NOT EXISTS (
            SELECT 1 FROM opentofu_workspaces w
            JOIN topology_profiles p ON p.profile_id=NEW.topology_profile_id
            JOIN topology_revisions r ON r.profile_id=p.profile_id
                AND r.revision_id=NEW.topology_revision_id
            WHERE w.workspace_id=NEW.workspace_id
              AND w.project_id=NEW.project_id AND w.lab_id=NEW.lab_id
              AND w.status IN ('ACTIVE','RECOVERY_REQUIRED')
              AND p.project_id=NEW.project_id AND p.status='ACTIVE'
              AND r.status='PUBLISHED'
              AND (
                (p.scope_type='PROJECT' AND p.lab_id IS NULL)
                OR (p.scope_type='LAB' AND p.lab_id=NEW.lab_id)
              )
              AND EXISTS (
                SELECT 1 FROM json_each(r.definition_json, '$.nodes') n
                WHERE json_extract(n.value, '$.id')=NEW.topology_node_id
              )
        )
        BEGIN SELECT RAISE(ABORT, 'infrastructure resource binding must target a published topology node in the same Project/Lab'); END""")
    op.execute("""CREATE TRIGGER trg_infra_binding_identity_immutable
        BEFORE UPDATE OF binding_id,workspace_id,project_id,lab_id,resource_address,resource_type,
            topology_profile_id,topology_revision_id,topology_node_id,created_at,created_by
        ON infrastructure_resource_bindings
        BEGIN SELECT RAISE(ABORT, 'infrastructure resource bindings are immutable'); END""")
    op.execute("""CREATE TRIGGER trg_infra_binding_state_transition
        BEFORE UPDATE OF status,superseded_by ON infrastructure_resource_bindings
        WHEN NOT (
            (OLD.status='ACTIVE' AND NEW.status='SUPERSEDED'
                AND OLD.superseded_by IS NULL AND NEW.superseded_by IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM infrastructure_resource_bindings next
                    WHERE next.binding_id=NEW.superseded_by
                      AND next.workspace_id=OLD.workspace_id
                      AND next.resource_address=OLD.resource_address
                      AND next.status='PENDING'
                ))
            OR (OLD.status='PENDING' AND NEW.status='ACTIVE'
                AND OLD.superseded_by IS NULL AND NEW.superseded_by IS NULL)
        )
        BEGIN SELECT RAISE(ABORT, 'infrastructure resource binding transition is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_infra_binding_no_delete
        BEFORE DELETE ON infrastructure_resource_bindings
        BEGIN SELECT RAISE(ABORT, 'infrastructure resource mapping history cannot be deleted'); END""")
    op.execute("""CREATE TRIGGER trg_infra_reconciliation_scope_insert
        BEFORE INSERT ON infrastructure_reconciliations
        WHEN NOT EXISTS (
            SELECT 1 FROM opentofu_workspaces w
            WHERE w.workspace_id=NEW.workspace_id AND w.project_id=NEW.project_id
              AND w.lab_id=NEW.lab_id AND w.status IN ('ACTIVE','RECOVERY_REQUIRED')
        )
        BEGIN SELECT RAISE(ABORT, 'infrastructure reconciliation scope must match an active or recovery workspace'); END""")
    op.execute("""CREATE TRIGGER trg_infra_reconciliations_immutable
        BEFORE UPDATE ON infrastructure_reconciliations
        BEGIN SELECT RAISE(ABORT, 'infrastructure reconciliation evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_infra_reconciliations_no_delete
        BEFORE DELETE ON infrastructure_reconciliations
        BEGIN SELECT RAISE(ABORT, 'infrastructure reconciliation history cannot be deleted'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_recovery_plan_scope_insert
        BEFORE INSERT ON opentofu_plans
        WHEN (
            (NEW.kind='RECOVERY' AND (
                NEW.reconciliation_id IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM infrastructure_reconciliations r
                    WHERE r.reconciliation_id=NEW.reconciliation_id
                      AND r.workspace_id=NEW.workspace_id
                      AND r.project_id=NEW.project_id
                      AND r.lab_id=NEW.lab_id
                )
            ))
            OR (NEW.kind<>'RECOVERY' AND NEW.reconciliation_id IS NOT NULL)
        )
        BEGIN SELECT RAISE(ABORT, 'OpenTofu recovery plans must reference a same-workspace reconciliation snapshot'); END""")
    op.execute("""CREATE TRIGGER trg_opentofu_recovery_plan_reference_immutable
        BEFORE UPDATE OF reconciliation_id ON opentofu_plans
        BEGIN SELECT RAISE(ABORT, 'OpenTofu recovery reconciliation reference is immutable'); END""")

    bind = op.get_bind()
    bind.execute(
        sa.text("INSERT OR IGNORE INTO permissions(code,resource,action,description) VALUES(:code,:resource,:action,:description)"),
        {
            "code": "infrastructure.reconcile", "resource": "infrastructure",
            "action": "reconcile",
            "description": "Refresh and compare OpenTofu state with mapped topology resources",
        },
    )
    for scope in ("GLOBAL", "PROJECT"):
        for role_name in ("ADMIN", "OWNER"):
            bind.execute(
                sa.text("INSERT OR IGNORE INTO role_permissions(role_id,permission_code) VALUES(:role,:permission)"),
                {"role": f"{scope.lower()}_{role_name.lower()}", "permission": "infrastructure.reconcile"},
            )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','32') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261124_22') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Infrastructure resource bindings, reconciliation snapshots and recovery references are audit-bearing; "
        "restore a verified pre-migration SQLite backup instead."
    )
