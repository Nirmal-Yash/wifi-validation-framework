"""Adopt the canonical Runner SQLite schema as the Alembic base.

Revision ID: 20261105_00
Revises: None
"""

from alembic import op

revision = "20261105_00"
down_revision = None
branch_labels = None
depends_on = None

BASE_SCHEMA_SQL = r"""
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


def upgrade():
    connection = op.get_bind()
    for statement in BASE_SCHEMA_SQL.split(";"):
        statement = statement.strip()
        if statement:
            connection.exec_driver_sql(statement)


def downgrade():
    raise RuntimeError(
        "The canonical schema base is not destructively reversible. "
        "Restore a verified pre-migration SQLite backup instead."
    )
