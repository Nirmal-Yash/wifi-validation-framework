"""Make Alembic authoritative for the canonical Runner schema.

Revision ID: 20261105_03
Revises: 20260924_02
"""

from alembic import op
import sqlalchemy as sa

revision = "20261105_03"
down_revision = "20260924_02"
branch_labels = None
depends_on = None


CANONICAL_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS environment_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    host_os TEXT NOT NULL,
    kernel TEXT NOT NULL,
    python_version TEXT NOT NULL,
    repository_commit TEXT NOT NULL,
    configuration_hash TEXT NOT NULL,
    tools_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    resolved_config_json TEXT NOT NULL,
    configuration_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    display_id TEXT NOT NULL UNIQUE,
    firmware_version TEXT NOT NULL,
    lab_id TEXT NOT NULL,
    validation_profile TEXT NOT NULL,
    selected_tests_json TEXT NOT NULL,
    test_definition_versions_json TEXT NOT NULL,
    resolved_config_json TEXT NOT NULL,
    configuration_hash TEXT NOT NULL,
    repository_commit TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    outcome TEXT,
    environment_health TEXT,
    environment_snapshot_id TEXT REFERENCES environment_snapshots(snapshot_id),
    config_snapshot_id TEXT REFERENCES config_snapshots(snapshot_id),
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    provenance TEXT NOT NULL DEFAULT 'NATIVE',
    failure_class TEXT,
    failure_reason TEXT,
    execution_pid INTEGER,
    source_run_id TEXT REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(run_id, number)
);

CREATE TABLE IF NOT EXISTS test_results (
    test_result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id) ON DELETE CASCADE,
    test_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    test_version TEXT NOT NULL,
    status TEXT NOT NULL,
    criticality TEXT NOT NULL,
    severity TEXT NOT NULL,
    evidence_state TEXT NOT NULL,
    error_reason TEXT,
    started_at TEXT,
    completed_at TEXT,
    provenance TEXT NOT NULL DEFAULT 'NATIVE',
    failure_class TEXT,
    failure_reason TEXT,
    execution_pid INTEGER,
    execution_metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS metrics (
    metric_id TEXT PRIMARY KEY,
    test_result_id TEXT NOT NULL REFERENCES test_results(test_result_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    authoritative INTEGER NOT NULL,
    UNIQUE(test_result_id, name)
);

CREATE TABLE IF NOT EXISTS samples (
    sample_id TEXT PRIMARY KEY,
    metric_id TEXT NOT NULL REFERENCES metrics(metric_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    value REAL NOT NULL,
    status TEXT NOT NULL,
    warmup INTEGER NOT NULL,
    retried INTEGER NOT NULL,
    captured_at TEXT,
    metadata_json TEXT NOT NULL,
    UNIQUE(metric_id, sequence)
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    test_result_id TEXT REFERENCES test_results(test_result_id) ON DELETE CASCADE,
    test_node_id TEXT,
    attempt_id TEXT REFERENCES attempts(attempt_id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    evidence_state TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    sensitivity_class TEXT NOT NULL DEFAULT 'INTERNAL',
    retain_until TEXT,
    soft_deleted_at TEXT,
    provenance TEXT NOT NULL DEFAULT 'NATIVE',
    failure_class TEXT,
    failure_reason TEXT,
    execution_pid INTEGER
);

CREATE TABLE IF NOT EXISTS lifecycle_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    attempt_id TEXT REFERENCES attempts(attempt_id),
    test_result_id TEXT REFERENCES test_results(test_result_id),
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_baselines (
    baseline_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    baseline_run_id TEXT NOT NULL REFERENCES runs(run_id),
    status TEXT NOT NULL,
    device_scope TEXT NOT NULL,
    firmware_major_scope TEXT NOT NULL,
    test_suite_version TEXT NOT NULL,
    lab_class TEXT NOT NULL,
    promoted_by TEXT NOT NULL,
    promoted_at TEXT NOT NULL,
    superseded_by TEXT,
    provenance TEXT NOT NULL DEFAULT 'NATIVE'
);

CREATE TABLE IF NOT EXISTS legacy_migration_records (
    source_table TEXT NOT NULL,
    source_row_id INTEGER NOT NULL,
    target_run_id TEXT NOT NULL,
    target_result_id TEXT,
    imported_at TEXT NOT NULL,
    PRIMARY KEY(source_table, source_row_id)
);

CREATE INDEX IF NOT EXISTS idx_attempts_run ON attempts(run_id);
CREATE INDEX IF NOT EXISTS idx_results_attempt ON test_results(attempt_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_events_run ON lifecycle_events(run_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_active_baseline_name
    ON run_baselines(name) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS sync_queue (
    envelope_id TEXT PRIMARY KEY,
    runner_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    state TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    leased_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sync_queue_ready
    ON sync_queue(state, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_sync_queue_run
    ON sync_queue(run_id);

CREATE TABLE IF NOT EXISTS release_waivers (
    waiver_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    target_id TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    audit_reference TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_waivers_target ON release_waivers(target_id, active, expires_at);
"""


def _columns(bind, table):
    return {item["name"] for item in sa.inspect(bind).get_columns(table)}


def _add_column(bind, table, column):
    if column.name not in _columns(bind, table):
        op.add_column(table, column)


def upgrade():
    bind = op.get_bind()
    # Also reconcile tables/indexes for databases already stamped at the
    # earlier Alembic 02 head, where the legacy runtime bootstrap may have
    # created part (but not all) of the current canonical schema.
    for statement in CANONICAL_SCHEMA_SQL.split(";"):
        statement = statement.strip()
        if statement:
            bind.exec_driver_sql(statement)

    additions = {
        "runs": (
            sa.Column("display_id", sa.String(), nullable=True),
            sa.Column("firmware_version", sa.String(), nullable=True),
            sa.Column("lab_id", sa.String(), nullable=True),
            sa.Column("validation_profile", sa.String(), nullable=True),
            sa.Column("selected_tests_json", sa.Text(), nullable=True),
            sa.Column("test_definition_versions_json", sa.Text(), nullable=True),
            sa.Column("resolved_config_json", sa.Text(), nullable=True),
            sa.Column("configuration_hash", sa.String(), nullable=True),
            sa.Column("repository_commit", sa.String(), nullable=True),
            sa.Column("lifecycle", sa.String(), nullable=True),
            sa.Column("outcome", sa.String(), nullable=True),
            sa.Column("environment_health", sa.String(), nullable=True),
            sa.Column("environment_snapshot_id", sa.String(), nullable=True),
            sa.Column("config_snapshot_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=True),
            sa.Column("started_at", sa.String(), nullable=True),
            sa.Column("completed_at", sa.String(), nullable=True),
            sa.Column("provenance", sa.String(), nullable=False, server_default="NATIVE"),
            sa.Column("failure_class", sa.String(), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("execution_pid", sa.Integer(), nullable=True),
            sa.Column("source_run_id", sa.String(), nullable=True),
        ),
        "test_results": (
            sa.Column("provenance", sa.String(), nullable=False, server_default="NATIVE"),
            sa.Column("failure_class", sa.String(), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("execution_pid", sa.Integer(), nullable=True),
            sa.Column("execution_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        ),
        "artifacts": (
            sa.Column("display_name", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.String(), nullable=True),
            sa.Column("sensitivity_class", sa.String(), nullable=False, server_default="INTERNAL"),
            sa.Column("retain_until", sa.String(), nullable=True),
            sa.Column("soft_deleted_at", sa.String(), nullable=True),
            sa.Column("provenance", sa.String(), nullable=False, server_default="NATIVE"),
            sa.Column("failure_class", sa.String(), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("execution_pid", sa.Integer(), nullable=True),
            sa.Column("test_node_id", sa.String(), nullable=True),
            sa.Column("attempt_id", sa.String(), nullable=True),
        ),
    }
    for table, columns in additions.items():
        for column in columns:
            _add_column(bind, table, column)

    # Preserve legacy run identities while supplying a usable display ID for
    # the unusually small historical helper schemas that only had run_id.
    if "display_id" in _columns(bind, "runs"):
        bind.exec_driver_sql(
            "UPDATE runs SET display_id = run_id "
            "WHERE display_id IS NULL OR display_id = ''"
        )
        bind.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_display_id ON runs(display_id)"
        )

    # Older tables sometimes predate declared foreign keys. Rebuild only the
    # affected table, using a naming convention for unnamed legacy UNIQUE/PK
    # constraints. The migration connection disables FK enforcement during
    # this controlled rebuild; DatabaseMigrationManager validates all FKs
    # immediately after Alembic completes.
    foreign_keys = {
        "runs": (
            ("environment_snapshot_id", "environment_snapshots", "snapshot_id", None),
            ("config_snapshot_id", "config_snapshots", "snapshot_id", None),
            ("source_run_id", "runs", "run_id", None),
        ),
        "test_results": (
            ("run_id", "runs", "run_id", "CASCADE"),
            ("attempt_id", "attempts", "attempt_id", "CASCADE"),
        ),
        "artifacts": (
            ("run_id", "runs", "run_id", "CASCADE"),
            ("test_result_id", "test_results", "test_result_id", "CASCADE"),
            ("attempt_id", "attempts", "attempt_id", "CASCADE"),
        ),
    }
    naming = {
        "pk": "pk_%(table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    }
    for table, required in foreign_keys.items():
        existing = {
            (item["from"], item["table"], item["to"])
            for item in bind.exec_driver_sql(f'PRAGMA foreign_key_list("{table}")').mappings()
        }
        missing = [
            item for item in required
            if (item[0], item[1], item[2]) not in existing
        ]
        if missing:
            with op.batch_alter_table(
                table, recreate="always", naming_convention=naming
            ) as batch:
                for column, parent, parent_column, on_delete in missing:
                    batch.create_foreign_key(
                        f"fk_{table}_{column}_{parent}",
                        parent,
                        [column],
                        [parent_column],
                        ondelete=on_delete,
                    )
    tables = set(sa.inspect(bind).get_table_names())
    if "baselines" in tables:
        baseline_columns = _columns(bind, "baselines")
        if "baseline_id" in baseline_columns:
            required = {
                "baseline_id", "name", "baseline_run_id", "status",
                "device_scope", "firmware_major_scope", "test_suite_version",
                "lab_class", "promoted_by", "promoted_at", "superseded_by",
            }
            missing = required - baseline_columns
            if missing:
                raise RuntimeError(
                    "legacy baselines table is missing required columns: "
                    + ", ".join(sorted(missing))
                )
            provenance_expr = (
                "provenance" if "provenance" in baseline_columns else "'NATIVE'"
            )
            bind.exec_driver_sql(
                f"""
                INSERT OR IGNORE INTO run_baselines(
                    baseline_id, name, baseline_run_id, status, device_scope,
                    firmware_major_scope, test_suite_version, lab_class,
                    promoted_by, promoted_at, superseded_by, provenance
                )
                SELECT baseline_id, name, baseline_run_id, status, device_scope,
                       firmware_major_scope, test_suite_version, lab_class,
                       promoted_by, promoted_at, superseded_by, {provenance_expr}
                FROM baselines
                """
            )
            archive_name = "legacy_baselines_archive"
            suffix = 2
            while archive_name in set(sa.inspect(bind).get_table_names()):
                archive_name = f"legacy_baselines_archive_{suffix}"
                suffix += 1
            bind.exec_driver_sql(
                f'ALTER TABLE baselines RENAME TO "{archive_name}"'
            )

    bind.exec_driver_sql(
        """
        INSERT INTO schema_meta(key, value)
        VALUES ('version', '12')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )
    bind.exec_driver_sql(
        """
        INSERT INTO schema_meta(key, value)
        VALUES ('migration_authority', 'alembic')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )
    bind.exec_driver_sql(
        """
        INSERT INTO schema_meta(key, value)
        VALUES ('alembic_revision', '20261105_03')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )


def downgrade():
    raise RuntimeError(
        "Schema governance revision is not destructively reversible. "
        "Restore a verified pre-migration SQLite backup instead."
    )
