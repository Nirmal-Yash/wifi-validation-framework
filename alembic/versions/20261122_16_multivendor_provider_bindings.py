"""Generalize the persisted topology binding for independent emulator providers.

Revision ID: 20261122_16
Revises: 20261117_15
"""
from alembic import op

revision = "20261122_16"
down_revision = "20261117_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the historical table as the single binding source of truth. The
    # legacy gns3_project_id column remains populated for older application
    # versions and is mirrored to the provider-neutral workspace column.
    op.execute(
        "ALTER TABLE gns3_lab_bindings ADD COLUMN provider_id TEXT NOT NULL "
        "DEFAULT 'gns3' CHECK(provider_id IN ('gns3','cml','eve-ng'))"
    )
    op.execute("ALTER TABLE gns3_lab_bindings ADD COLUMN provider_workspace_id TEXT")
    op.execute(
        "UPDATE gns3_lab_bindings SET provider_id='gns3', "
        "provider_workspace_id=gns3_project_id"
    )
    op.execute("""CREATE TRIGGER trg_provider_bindings_workspace_insert
        BEFORE INSERT ON gns3_lab_bindings
        WHEN NEW.provider_id NOT IN ('gns3','cml','eve-ng')
          OR NEW.provider_workspace_id IS NULL
          OR length(trim(NEW.provider_workspace_id)) < 1
          OR length(NEW.provider_workspace_id) > 512
        BEGIN SELECT RAISE(ABORT, 'provider binding identity is invalid'); END""")
    op.execute("""CREATE TRIGGER trg_provider_bindings_workspace_update
        BEFORE UPDATE OF provider_id,provider_workspace_id,gns3_project_id ON gns3_lab_bindings
        WHEN NEW.provider_id NOT IN ('gns3','cml','eve-ng')
          OR NEW.provider_workspace_id IS NULL
          OR length(trim(NEW.provider_workspace_id)) < 1
          OR length(NEW.provider_workspace_id) > 512
          OR NEW.provider_workspace_id <> NEW.gns3_project_id
        BEGIN SELECT RAISE(ABORT, 'provider binding identity must be valid and mirrored'); END""")
    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','26') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261122_16') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_provider_bindings_workspace_update")
    op.execute("DROP TRIGGER IF EXISTS trg_provider_bindings_workspace_insert")
    op.execute("ALTER TABLE gns3_lab_bindings DROP COLUMN provider_workspace_id")
    op.execute("ALTER TABLE gns3_lab_bindings DROP COLUMN provider_id")
    bind = op.get_bind()
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('version','25') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    bind.exec_driver_sql(
        "INSERT INTO schema_meta(key,value) VALUES('alembic_revision','20261117_15') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
