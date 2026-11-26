"""Add immutable Project/Lab-scoped managed-device network observations.

Revision ID: 20261124_23
Revises: 20261124_22
"""
from alembic import op
import sqlalchemy as sa

revision = "20261124_23"
down_revision = "20261124_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_observation_snapshots",
        sa.Column("observation_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("lab_id", sa.String(128), nullable=False),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("captured_at", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("observed_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.device_id"], ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(trim(source)) BETWEEN 1 AND 80",
            name="ck_device_observation_source",
        ),
        sa.CheckConstraint(
            "length(payload_sha256)=64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_device_observation_hash",
        ),
        sa.CheckConstraint(
            "length(payload_json) BETWEEN 2 AND 2097152",
            name="ck_device_observation_payload_size",
        ),
        sa.CheckConstraint(
            "length(trim(observed_by)) BETWEEN 1 AND 128",
            name="ck_device_observation_actor",
        ),
    )
    op.create_index(
        "idx_device_observations_device_captured",
        "device_observation_snapshots",
        ["device_id", "captured_at", "observation_id"],
    )
    op.create_index(
        "idx_device_observations_project_lab_captured",
        "device_observation_snapshots",
        ["project_id", "lab_id", "captured_at"],
    )

    op.create_table(
        "provider_observation_snapshots",
        sa.Column("observation_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("lab_id", sa.String(128), nullable=False),
        sa.Column("binding_id", sa.String(32), nullable=False),
        sa.Column("provider_id", sa.String(16), nullable=False),
        sa.Column("observed_at", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("observed_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "lab_id"], ["labs.project_id", "labs.lab_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["gns3_lab_bindings.binding_id"], ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "provider_id IN ('gns3','cml','eve-ng')",
            name="ck_provider_observation_provider",
        ),
        sa.CheckConstraint(
            "length(payload_sha256)=64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_provider_observation_hash",
        ),
        sa.CheckConstraint(
            "length(payload_json) BETWEEN 2 AND 2097152",
            name="ck_provider_observation_payload_size",
        ),
        sa.CheckConstraint(
            "length(trim(observed_by)) BETWEEN 1 AND 128",
            name="ck_provider_observation_actor",
        ),
    )
    op.create_index(
        "idx_provider_observations_lab_observed",
        "provider_observation_snapshots",
        ["lab_id", "observed_at", "observation_id"],
    )
    op.create_index(
        "idx_provider_observations_project_observed",
        "provider_observation_snapshots",
        ["project_id", "observed_at"],
    )

    op.execute("""CREATE TRIGGER trg_provider_observations_scope_insert
        BEFORE INSERT ON provider_observation_snapshots
        WHEN NOT EXISTS (
            SELECT 1 FROM gns3_lab_bindings b
            JOIN labs l ON l.project_id=b.project_id AND l.lab_id=b.lab_id
            WHERE b.binding_id=NEW.binding_id
              AND b.project_id=NEW.project_id AND b.lab_id=NEW.lab_id
              AND b.provider_id=NEW.provider_id AND b.status='ACTIVE'
              AND l.status='ACTIVE'
        )
        BEGIN SELECT RAISE(ABORT, 'provider observation must reference an active provider binding in the exact Project/Lab'); END""")
    op.execute("""CREATE TRIGGER trg_provider_observations_immutable
        BEFORE UPDATE ON provider_observation_snapshots
        BEGIN SELECT RAISE(ABORT, 'provider observation evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_provider_observations_no_delete
        BEFORE DELETE ON provider_observation_snapshots
        BEGIN SELECT RAISE(ABORT, 'provider observation history cannot be deleted'); END""")

    op.execute("""CREATE TRIGGER trg_device_observations_scope_insert
        BEFORE INSERT ON device_observation_snapshots
        WHEN NOT EXISTS (
            SELECT 1 FROM devices d JOIN labs l
              ON l.project_id=d.project_id AND l.lab_id=d.lab_id
            WHERE d.device_id=NEW.device_id
              AND d.project_id=NEW.project_id AND d.lab_id=NEW.lab_id
              AND d.status='ACTIVE' AND l.status='ACTIVE'
        )
        BEGIN SELECT RAISE(ABORT, 'device observation must reference an active Device in the exact Project/Lab'); END""")
    op.execute("""CREATE TRIGGER trg_device_observations_immutable
        BEFORE UPDATE ON device_observation_snapshots
        BEGIN SELECT RAISE(ABORT, 'device observation evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_device_observations_no_delete
        BEFORE DELETE ON device_observation_snapshots
        BEGIN SELECT RAISE(ABORT, 'device observation history cannot be deleted'); END""")

    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','33') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261124_23') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Device observation snapshots are immutable measurement evidence; "
        "restore a verified pre-migration SQLite backup instead."
    )
