"""Runtime contract for the Alembic-managed SQLite schema.

The migration scripts define how this contract evolves. This module verifies
that the physical database matches the required head; it never repairs drift.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


EXPECTED_TABLE_COLUMNS = {
    "schema_meta": ("key", "value"),
    "environment_snapshots": (
        "snapshot_id", "host_os", "kernel", "python_version",
        "repository_commit", "configuration_hash", "tools_json",
    ),
    "config_snapshots": (
        "snapshot_id", "resolved_config_json", "configuration_hash",
    ),
    "runs": (
        "run_id", "display_id", "firmware_version", "lab_id",
        "validation_profile", "selected_tests_json",
        "test_definition_versions_json", "resolved_config_json",
        "configuration_hash", "repository_commit", "lifecycle", "outcome",
        "environment_health", "environment_snapshot_id", "config_snapshot_id",
        "created_at", "started_at", "completed_at", "provenance",
        "failure_class", "failure_reason", "execution_pid", "source_run_id", "project_id",
    ),
    "attempts": (
        "attempt_id", "run_id", "number", "started_at", "completed_at",
    ),
    "test_results": (
        "test_result_id", "run_id", "attempt_id", "test_id", "node_id",
        "test_version", "status", "criticality", "severity", "evidence_state",
        "error_reason", "started_at", "completed_at", "provenance",
        "failure_class", "failure_reason", "execution_pid",
        "execution_metadata_json",
    ),
    "metrics": (
        "metric_id", "test_result_id", "name", "unit", "authoritative",
    ),
    "samples": (
        "sample_id", "metric_id", "sequence", "value", "status", "warmup",
        "retried", "captured_at", "metadata_json",
    ),
    "artifacts": (
        "artifact_id", "run_id", "test_result_id", "test_node_id", "attempt_id",
        "artifact_type", "path", "sha256", "size_bytes", "evidence_state",
        "display_name", "created_at", "sensitivity_class", "retain_until",
        "soft_deleted_at", "provenance", "failure_class", "failure_reason",
        "execution_pid",
    ),
    "lifecycle_events": (
        "event_id", "run_id", "attempt_id", "test_result_id", "event_type",
        "occurred_at", "details_json",
    ),
    "run_baselines": (
        "baseline_id", "name", "baseline_run_id", "status", "device_scope",
        "firmware_major_scope", "test_suite_version", "lab_class",
        "promoted_by", "promoted_at", "superseded_by", "provenance",
    ),
    "legacy_migration_records": (
        "source_table", "source_row_id", "target_run_id", "target_result_id",
        "imported_at",
    ),
    "sync_queue": (
        "envelope_id", "runner_id", "run_id", "kind", "schema_version",
        "idempotency_key", "payload_json", "payload_sha256", "state",
        "attempt_count", "next_attempt_at", "leased_at", "last_error",
        "created_at", "updated_at",
    ),
    "release_waivers": (
        "waiver_id", "scope", "target_id", "issue_code", "reason",
        "created_by", "created_at", "expires_at", "audit_reference", "active",
    ),
    "organizations": ("organization_id", "slug", "name", "status", "created_at", "updated_at"),
    "projects": ("project_id", "organization_id", "slug", "name", "status", "created_at", "updated_at"),
    "labs": ("lab_id", "project_id", "name", "provider_id", "topology_version", "status", "created_at", "updated_at"),
    "project_memberships": ("username", "project_id", "role", "created_at", "created_by"),
    "users": ("username", "email", "display_name", "password_hash", "status", "workspace_scope", "created_at", "updated_at", "created_by", "activated_at", "password_changed_at"),
    "roles": ("role_id", "name", "scope_type", "description", "is_system", "created_at", "updated_at", "created_by"),
    "permissions": ("code", "resource", "action", "description"),
    "role_permissions": ("role_id", "permission_code"),
    "role_assignments": ("username", "role_id", "scope_type", "scope_id", "created_at", "created_by"),
    "user_sessions": ("session_hash", "username", "created_at", "last_seen_at", "expires_at", "revoked_at"),
    "invitation_tokens": ("token_hash", "username", "created_at", "expires_at", "created_by", "consumed_at"),
    "password_reset_tokens": ("token_hash", "username", "created_at", "expires_at", "created_by", "consumed_at"),
    "audit_events": ("audit_id", "actor_username", "action", "resource_type", "resource_id", "details_json", "occurred_at"),
    "managed_credentials": ("credential_id", "project_id", "device_id", "label", "credential_type", "username", "secret_provider", "secret_reference", "status", "verification_status", "last_verified_at", "verification_summary", "rotated_at", "created_at", "updated_at", "created_by", "updated_by"),
    "configuration_schemas": ("schema_record_id", "project_id", "schema_id", "version", "name", "definition_json", "status", "created_at", "created_by"),
}

EXPECTED_TRIGGERS = (
    "trg_runs_project_scope_insert",
    "trg_runs_project_scope_update",
    "trg_projects_prevent_delete_with_runs",
    "trg_audit_events_no_update",
    "trg_audit_events_no_delete",
    "trg_managed_credentials_no_delete",
    "trg_configuration_schemas_no_delete",
)

EXPECTED_INDEXES = (
    "idx_attempts_run",
    "idx_results_attempt",
    "idx_artifacts_run",
    "idx_events_run",
    "idx_active_baseline_name",
    "idx_sync_queue_ready",
    "idx_sync_queue_run",
    "idx_waivers_target",
    "idx_projects_organization",
    "idx_labs_project",
    "idx_runs_project_created",
    "idx_project_memberships_project",
    "idx_users_status",
    "uq_users_email",
    "idx_role_assignments_role",
    "idx_role_assignments_scope",
    "idx_user_sessions_user",
    "idx_invitation_user",
    "idx_password_reset_user",
    "idx_audit_events_time",
    "idx_audit_events_resource",
    "idx_credentials_project_device_status",
    "idx_configuration_schemas_project_schema",
)

EXPECTED_FOREIGN_KEYS = {
    ("runs", "environment_snapshot_id", "environment_snapshots", "snapshot_id"),
    ("runs", "config_snapshot_id", "config_snapshots", "snapshot_id"),
    ("runs", "source_run_id", "runs", "run_id"),
    ("attempts", "run_id", "runs", "run_id"),
    ("test_results", "run_id", "runs", "run_id"),
    ("test_results", "attempt_id", "attempts", "attempt_id"),
    ("metrics", "test_result_id", "test_results", "test_result_id"),
    ("samples", "metric_id", "metrics", "metric_id"),
    ("artifacts", "run_id", "runs", "run_id"),
    ("artifacts", "test_result_id", "test_results", "test_result_id"),
    ("artifacts", "attempt_id", "attempts", "attempt_id"),
    ("lifecycle_events", "run_id", "runs", "run_id"),
    ("lifecycle_events", "attempt_id", "attempts", "attempt_id"),
    ("lifecycle_events", "test_result_id", "test_results", "test_result_id"),
    ("run_baselines", "baseline_run_id", "runs", "run_id"),
    ("sync_queue", "run_id", "runs", "run_id"),
    ("projects", "organization_id", "organizations", "organization_id"),
    ("managed_credentials", "project_id", "projects", "project_id"),
    ("configuration_schemas", "project_id", "projects", "project_id"),
    ("labs", "project_id", "projects", "project_id"),
    ("project_memberships", "project_id", "projects", "project_id"),
    ("role_permissions", "role_id", "roles", "role_id"),
    ("role_permissions", "permission_code", "permissions", "code"),
    ("role_assignments", "role_id", "roles", "role_id"),
    ("user_sessions", "username", "users", "username"),
    ("invitation_tokens", "username", "users", "username"),
    ("password_reset_tokens", "username", "users", "username"),
}


@dataclass(frozen=True, slots=True)
class SchemaDriftReport:
    missing_tables: tuple[str, ...] = ()
    missing_columns: tuple[str, ...] = ()
    missing_indexes: tuple[str, ...] = ()
    missing_foreign_keys: tuple[str, ...] = ()
    foreign_key_violations: tuple[str, ...] = ()
    metadata_errors: tuple[str, ...] = ()
    missing_triggers: tuple[str, ...] = ()

    @property
    def is_clean(self) -> bool:
        return not any((
            self.missing_tables,
            self.missing_columns,
            self.missing_indexes,
            self.missing_foreign_keys,
            self.foreign_key_violations,
            self.metadata_errors,
            self.missing_triggers,
        ))

    def as_dict(self) -> dict:
        return {
            "clean": self.is_clean,
            "missing_tables": list(self.missing_tables),
            "missing_columns": list(self.missing_columns),
            "missing_indexes": list(self.missing_indexes),
            "missing_foreign_keys": list(self.missing_foreign_keys),
            "foreign_key_violations": list(self.foreign_key_violations),
            "metadata_errors": list(self.metadata_errors),
            "missing_triggers": list(self.missing_triggers),
        }


def inspect_sqlite_schema(
    connection: sqlite3.Connection,
    *,
    current_revision: str | None,
    head_revision: str,
) -> SchemaDriftReport:
    connection.row_factory = sqlite3.Row
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing_tables = []
    missing_columns = []
    for table, required in EXPECTED_TABLE_COLUMNS.items():
        if table not in tables:
            missing_tables.append(table)
            continue
        actual = {
            row["name"]
            for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
        missing_columns.extend(
            f"{table}.{column}" for column in required if column not in actual
        )

    actual_indexes = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    missing_indexes = [name for name in EXPECTED_INDEXES if name not in actual_indexes]

    actual_foreign_keys = set()
    for table in EXPECTED_TABLE_COLUMNS:
        if table not in tables:
            continue
        for row in connection.execute(f'PRAGMA foreign_key_list("{table}")').fetchall():
            actual_foreign_keys.add(
                (table, row["from"], row["table"], row["to"])
            )
    missing_foreign_keys = [
        f"{table}.{column} -> {parent}.{parent_column}"
        for table, column, parent, parent_column in sorted(EXPECTED_FOREIGN_KEYS)
        if (table, column, parent, parent_column) not in actual_foreign_keys
    ]

    violations = tuple(
        f"{row[0]}:{row[1]} -> {row[2]} (rowid={row[3]})"
        for row in connection.execute("PRAGMA foreign_key_check").fetchall()
    ) if tables else ()

    actual_triggers = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    missing_triggers = [
        name for name in EXPECTED_TRIGGERS if name not in actual_triggers
    ]

    metadata_errors = []
    if current_revision != head_revision:
        metadata_errors.append(
            f"Alembic revision is {current_revision or 'unversioned'}; expected {head_revision}"
        )
    if "schema_meta" in tables:
        metadata = {
            row["key"]: row["value"]
            for row in connection.execute(
                "SELECT key, value FROM schema_meta"
            ).fetchall()
        }
        if metadata.get("migration_authority") != "alembic":
            metadata_errors.append("schema_meta.migration_authority is not 'alembic'")
        if metadata.get("alembic_revision") != head_revision:
            metadata_errors.append(
                f"schema_meta.alembic_revision is {metadata.get('alembic_revision')!r}; "
                f"expected {head_revision!r}"
            )
        if metadata.get("version") != "17":
            metadata_errors.append(
                f"schema_meta.version is {metadata.get('version')!r}; expected '17'"
            )
    else:
        metadata_errors.append("schema_meta table is missing")

    return SchemaDriftReport(
        missing_tables=tuple(sorted(missing_tables)),
        missing_columns=tuple(sorted(missing_columns)),
        missing_indexes=tuple(sorted(missing_indexes)),
        missing_foreign_keys=tuple(sorted(missing_foreign_keys)),
        foreign_key_violations=violations,
        metadata_errors=tuple(metadata_errors),
        missing_triggers=tuple(sorted(missing_triggers)),
    )
