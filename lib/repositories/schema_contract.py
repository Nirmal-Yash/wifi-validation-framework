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
    "configuration_profiles": ("profile_id", "project_id", "name", "description", "scope_type", "scope_id", "schema_record_id", "status", "created_at", "updated_at", "created_by", "updated_by"),
    "configuration_revisions": ("revision_id", "profile_id", "schema_record_id", "revision_number", "values_json", "configuration_hash", "provenance_json", "parent_revision_id", "status", "created_at", "created_by", "published_at", "published_by"),
    "configuration_assignments": ("assignment_id", "project_id", "target_type", "target_id", "profile_id", "revision_id", "assigned_at", "assigned_by"),
    "devices": ("device_id", "project_id", "lab_id", "device_key", "name", "device_type", "host", "port", "vendor", "model", "username", "credential_id", "capabilities_json", "metadata_json", "status", "created_at", "updated_at", "created_by", "updated_by"),
    "topology_profiles": ("profile_id", "project_id", "name", "description", "scope_type", "scope_id", "lab_id", "status", "created_at", "updated_at", "created_by", "updated_by"),
    "topology_revisions": ("revision_id", "profile_id", "revision_number", "definition_json", "content_sha256", "status", "created_at", "created_by", "published_at", "published_by"),
    "topology_native_sources": ("source_id", "project_id", "profile_id", "revision_id", "format", "format_version", "filename", "sha256", "size_bytes", "source_bytes", "codec_name", "codec_version", "mapping_json", "compatibility_report_json", "imported_at", "imported_by"),
    "topology_source_artifacts": ("source_id", "project_id", "profile_id", "topology_revision_id", "topology_content_sha256", "format_id", "format_version", "filename", "sha256", "size_bytes", "source_bytes", "codec_name", "codec_version", "metadata_json", "imported_at", "imported_by"),
    "topology_source_assets": ("asset_id", "source_id", "relative_path", "media_type", "sha256", "size_bytes", "content_bytes", "created_at"),
    "topology_presentation_revisions": ("presentation_id", "project_id", "profile_id", "topology_revision_id", "revision_number", "schema_version", "topology_content_sha256", "presentation_json", "presentation_sha256", "source_artifact_id", "status", "created_at", "created_by", "published_at", "published_by"),
    "network_intent_profiles": ("profile_id", "project_id", "topology_profile_id", "name", "description", "scope_type", "scope_id", "lab_id", "status", "created_at", "updated_at", "created_by", "updated_by"),
    "network_intent_revisions": ("revision_id", "profile_id", "topology_revision_id", "topology_content_sha256", "schema_version", "revision_number", "definition_json", "intent_sha256", "provenance_json", "parent_revision_id", "status", "created_at", "created_by", "published_at", "published_by"),
    "device_capability_reports": ("report_id", "project_id", "device_id", "provider_id", "platform", "software_version", "adapter_name", "adapter_version", "source_type", "capabilities_json", "capability_sha256", "observed_at", "recorded_at", "recorded_by"),
    "ansible_automation_plans": ("plan_id", "project_id", "lab_id", "profile_id", "revision_id", "plan_sha256", "plan_json", "validation_json", "status", "created_at", "updated_at", "created_by", "approved_at", "approved_by"),
    "ansible_automation_approvals": ("approval_id", "plan_id", "plan_sha256", "approved_by", "confirmed_at"),
    "ansible_automation_executions": ("execution_id", "plan_id", "approval_id", "plan_sha256", "status", "result_json", "started_at", "completed_at", "executed_by"),
    "gns3_lab_bindings": ("binding_id", "project_id", "lab_id", "endpoint_url", "gns3_project_id", "controller_device_id", "credential_id", "status", "created_at", "updated_at", "created_by", "updated_by", "provider_id", "provider_workspace_id"),
    "topology_provider_mappings": ("mapping_id", "project_id", "lab_id", "profile_id", "resource_type", "logical_id", "provider_resource_id", "template_id", "created_at", "updated_at"),
    "topology_apply_records": ("apply_id", "project_id", "lab_id", "profile_id", "revision_id", "content_sha256", "status", "plan_json", "observed_before_json", "observed_after_json", "result_json", "created_at", "started_at", "completed_at", "created_by"),
    "device_configuration_deployments": ("deployment_id", "project_id", "lab_id", "device_id", "profile_id", "revision_id", "schema_record_id", "configuration_hash", "status", "plan_json", "result_json", "created_at", "started_at", "completed_at", "created_by"),
    "performance_policy_profiles": ("policy_profile_id", "project_id", "name", "description", "scope_type", "scope_id", "status", "created_at", "updated_at", "created_by", "updated_by"),
    "performance_policy_revisions": ("revision_id", "policy_profile_id", "revision_number", "policy_json", "policy_hash", "status", "created_at", "created_by", "published_at", "published_by"),
    "performance_policy_assignments": ("assignment_id", "project_id", "lab_id", "policy_profile_id", "revision_id", "assigned_at", "assigned_by"),
    "pipeline_definitions": ("pipeline_id", "project_id", "lab_id", "name", "description", "status", "created_at", "updated_at", "created_by", "updated_by"),
    "pipeline_revisions": ("revision_id", "pipeline_id", "revision_number", "definition_json", "definition_sha256", "status", "created_at", "created_by", "published_at", "published_by"),
    "pipeline_executions": ("execution_id", "project_id", "lab_id", "pipeline_id", "revision_id", "definition_sha256", "status", "inputs_json", "result_json", "linked_run_id", "idempotency_key", "created_at", "started_at", "completed_at", "created_by", "worker_id", "lease_expires_at", "heartbeat_at", "attempt_count", "last_error"),
    "pipeline_steps": ("execution_id", "step_key", "ordinal", "step_type", "status", "definition_json", "result_json", "max_attempts", "attempt_count", "timeout_seconds", "next_attempt_at", "worker_id", "lease_expires_at", "created_at", "started_at", "completed_at", "last_error"),
    "pipeline_step_attempts": ("step_attempt_id", "execution_id", "step_key", "attempt_number", "status", "worker_id", "started_at", "completed_at", "result_json", "error_summary"),
    "opentofu_workspaces": (
        "workspace_id", "project_id", "lab_id", "name", "module_key", "module_sha256",
        "variables_json", "status", "created_at", "updated_at", "created_by",
    ),
    "opentofu_plans": (
        "plan_id", "workspace_id", "project_id", "lab_id", "kind", "plan_sha256",
        "plan_file", "summary_json", "status", "created_at", "created_by",
        "approved_at", "approved_by", "reconciliation_id",
    ),
    "opentofu_approvals": (
        "approval_id", "plan_id", "plan_sha256", "approved_by", "confirmed_at",
    ),
    "opentofu_executions": (
        "execution_id", "plan_id", "plan_sha256", "status", "result_json",
        "started_at", "completed_at", "executed_by",
    ),
    "infrastructure_resource_bindings": (
        "binding_id", "workspace_id", "project_id", "lab_id", "resource_address",
        "resource_type", "topology_profile_id", "topology_revision_id", "topology_node_id",
        "status", "superseded_by", "created_at", "created_by",
    ),
    "infrastructure_reconciliations": (
        "reconciliation_id", "workspace_id", "project_id", "lab_id", "status",
        "state_sha256", "refresh_plan_sha256", "resource_count", "drift_count",
        "orphan_count", "missing_count", "details_json", "created_at", "created_by",
    ),
}

EXPECTED_TRIGGERS = (
    "trg_runs_project_scope_insert",
    "trg_runs_project_scope_update",
    "trg_projects_prevent_delete_with_runs",
    "trg_audit_events_no_update",
    "trg_audit_events_no_delete",
    "trg_managed_credentials_no_delete",
    "trg_configuration_schemas_no_delete",
    "trg_configuration_revisions_immutable",
    "trg_configuration_revisions_no_delete",
    "trg_configuration_assignments_no_delete",
    "trg_devices_credential_scope_insert",
    "trg_devices_credential_scope_update",
    "trg_devices_no_delete",
    "trg_performance_policy_revisions_immutable",
    "trg_performance_policy_revisions_no_delete",
    "trg_performance_policy_assignments_no_delete",
    "trg_topology_profiles_no_delete",
    "trg_topology_revisions_immutable",
    "trg_topology_revisions_no_delete",
    "trg_topology_native_sources_scope_insert",
    "trg_topology_native_sources_immutable",
    "trg_topology_native_sources_no_delete",
    "trg_network_intent_profiles_scope_insert",
    "trg_network_intent_profiles_no_delete",
    "trg_network_intent_profiles_identity_immutable",
    "trg_network_intent_revisions_scope_insert",
    "trg_network_intent_revisions_immutable",
    "trg_network_intent_revisions_published_immutable",
    "trg_network_intent_revisions_no_delete",
    "trg_device_capability_reports_scope_insert",
    "trg_device_capability_reports_immutable",
    "trg_device_capability_reports_no_delete",
    "trg_ansible_automation_plans_scope_insert",
    "trg_ansible_automation_plans_identity_immutable",
    "trg_ansible_automation_plans_state_transition",
    "trg_ansible_automation_plans_no_delete",
    "trg_ansible_automation_plans_approval_immutable",
    "trg_ansible_automation_approvals_scope_insert",
    "trg_ansible_automation_approvals_immutable",
    "trg_ansible_automation_approvals_no_delete",
    "trg_ansible_automation_executions_scope_insert",
    "trg_ansible_automation_executions_identity_immutable",
    "trg_ansible_automation_executions_state_transition",
    "trg_ansible_automation_executions_no_delete",
    "trg_ansible_automation_executions_final_immutable",
    "trg_gns3_bindings_credential_scope_insert",
    "trg_gns3_bindings_credential_scope_update",
    "trg_gns3_bindings_no_delete",
    "trg_provider_bindings_workspace_insert",
    "trg_provider_bindings_workspace_update",
    "trg_topology_provider_mappings_scope_insert",
    "trg_topology_provider_mappings_scope_update",
    "trg_topology_provider_mappings_no_delete",
    "trg_topology_apply_scope_insert",
    "trg_topology_apply_identity_immutable",
    "trg_topology_apply_no_delete",
    "trg_device_config_deployments_scope_insert",
    "trg_device_config_deployments_identity_immutable",
    "trg_device_config_deployments_final_immutable",
    "trg_device_config_deployments_no_delete",
    "trg_pipeline_definitions_no_delete",
    "trg_pipeline_revisions_published_immutable",
    "trg_pipeline_revisions_no_delete",
    "trg_pipeline_execution_scope_insert",
    "trg_pipeline_execution_run_scope_insert",
    "trg_pipeline_execution_run_scope_update",
    "trg_pipeline_execution_identity_immutable",
    "trg_pipeline_executions_no_delete",
    "trg_pipeline_steps_identity_immutable",
    "trg_pipeline_steps_no_delete",
    "trg_pipeline_step_attempts_final_immutable",
    "trg_pipeline_step_attempts_no_delete",
    "trg_topology_source_artifacts_scope_insert",
    "trg_topology_source_artifacts_immutable",
    "trg_topology_source_artifacts_no_delete",
    "trg_topology_source_assets_immutable",
    "trg_topology_source_assets_no_delete",
    "trg_topology_presentation_scope_insert",
    "trg_topology_presentation_identity_immutable",
    "trg_topology_presentation_state_transition",
    "trg_topology_presentation_publish_scope",
    "trg_topology_presentation_publish_metadata",
    "trg_topology_presentation_published_immutable",
    "trg_topology_presentation_no_delete",
    "trg_opentofu_workspace_scope_insert",
    "trg_opentofu_workspace_identity_immutable",
    "trg_opentofu_workspace_state_transition",
    "trg_opentofu_workspace_no_delete",
    "trg_opentofu_plan_scope_insert",
    "trg_opentofu_plan_identity_immutable",
    "trg_opentofu_plan_state_transition",
    "trg_opentofu_plan_approval_immutable",
    "trg_opentofu_plan_no_delete",
    "trg_opentofu_approval_scope_insert",
    "trg_opentofu_approvals_immutable",
    "trg_opentofu_approvals_no_delete",
    "trg_opentofu_execution_scope_insert",
    "trg_opentofu_execution_identity_immutable",
    "trg_opentofu_execution_state_transition",
    "trg_opentofu_execution_final_immutable",
    "trg_opentofu_executions_no_delete",
    "trg_infra_binding_scope_insert",
    "trg_infra_binding_identity_immutable",
    "trg_infra_binding_state_transition",
    "trg_infra_binding_no_delete",
    "trg_infra_reconciliation_scope_insert",
    "trg_infra_reconciliations_immutable",
    "trg_infra_reconciliations_no_delete",
    "trg_opentofu_recovery_plan_scope_insert",
    "trg_opentofu_recovery_plan_reference_immutable",
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
    "idx_configuration_profiles_project_scope",
    "idx_configuration_revisions_profile_number",
    "idx_configuration_assignments_target",
    "idx_devices_project_lab_status",
    "idx_devices_credential",
    "uq_labs_project_lab",
    "idx_performance_policy_profiles_project_scope",
    "idx_performance_policy_revisions_profile_number",
    "idx_performance_policy_assignments_lab",
    "idx_topology_profiles_project_scope",
    "idx_topology_revisions_profile_number",
    "idx_topology_native_sources_profile_imported",
    "idx_topology_native_sources_revision",
    "idx_network_intent_profiles_project_scope",
    "idx_network_intent_profiles_topology",
    "idx_network_intent_revisions_profile_number",
    "idx_network_intent_revisions_topology",
    "idx_device_capability_reports_device_observed",
    "idx_device_capability_reports_project_observed",
    "idx_ansible_automation_plans_project_created",
    "idx_ansible_automation_plans_revision",
    "idx_ansible_automation_approvals_plan",
    "idx_ansible_automation_executions_plan",
    "idx_gns3_bindings_project_lab",
    "idx_topology_provider_mappings_lab",
    "idx_topology_apply_lab_created",
    "idx_topology_apply_profile_revision",
    "idx_device_config_deployments_target",
    "idx_device_config_deployments_revision",
    "idx_pipeline_definitions_project_lab",
    "idx_pipeline_revisions_pipeline_number",
    "idx_pipeline_executions_queue",
    "idx_pipeline_executions_project_lab",
    "idx_pipeline_executions_pipeline",
    "idx_pipeline_executions_linked_run",
    "idx_pipeline_steps_ready",
    "idx_pipeline_step_attempts_step",
    "idx_topology_source_artifacts_profile_imported",
    "idx_topology_source_artifacts_revision",
    "idx_topology_source_assets_source",
    "idx_topology_presentation_profile_revision",
    "idx_topology_presentation_topology_revision",
    "idx_topology_presentation_source",
    "idx_opentofu_workspaces_project_created",
    "idx_opentofu_workspaces_lab",
    "idx_opentofu_plans_project_created",
    "idx_opentofu_plans_workspace",
    "idx_opentofu_approvals_plan",
    "idx_opentofu_executions_plan",
    "uq_topology_revision_profile_revision",
    "uq_infra_resource_binding_active",
    "idx_infra_resource_bindings_workspace",
    "idx_infra_resource_bindings_topology",
    "idx_infra_reconciliations_workspace_created",
    "idx_infra_reconciliations_project_created",
    "idx_opentofu_plans_reconciliation",
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
    ("configuration_profiles", "project_id", "projects", "project_id"),
    ("configuration_profiles", "schema_record_id", "configuration_schemas", "schema_record_id"),
    ("configuration_revisions", "profile_id", "configuration_profiles", "profile_id"),
    ("configuration_revisions", "schema_record_id", "configuration_schemas", "schema_record_id"),
    ("configuration_revisions", "parent_revision_id", "configuration_revisions", "revision_id"),
    ("configuration_assignments", "project_id", "projects", "project_id"),
    ("configuration_assignments", "profile_id", "configuration_profiles", "profile_id"),
    ("configuration_assignments", "revision_id", "configuration_revisions", "revision_id"),
    ("devices", "credential_id", "managed_credentials", "credential_id"),
    ("devices", "project_id", "labs", "project_id"),
    ("devices", "lab_id", "labs", "lab_id"),
    ("topology_profiles", "project_id", "projects", "project_id"),
    ("topology_profiles", "lab_id", "labs", "lab_id"),
    ("topology_revisions", "profile_id", "topology_profiles", "profile_id"),
    ("topology_native_sources", "project_id", "projects", "project_id"),
    ("topology_native_sources", "profile_id", "topology_profiles", "profile_id"),
    ("topology_native_sources", "revision_id", "topology_revisions", "revision_id"),
    ("topology_source_artifacts", "project_id", "projects", "project_id"),
    ("topology_source_artifacts", "profile_id", "topology_profiles", "profile_id"),
    ("topology_source_artifacts", "topology_revision_id", "topology_revisions", "revision_id"),
    ("topology_source_assets", "source_id", "topology_source_artifacts", "source_id"),
    ("topology_presentation_revisions", "project_id", "projects", "project_id"),
    ("topology_presentation_revisions", "profile_id", "topology_profiles", "profile_id"),
    ("topology_presentation_revisions", "topology_revision_id", "topology_revisions", "revision_id"),
    ("topology_presentation_revisions", "source_artifact_id", "topology_source_artifacts", "source_id"),
    ("network_intent_profiles", "project_id", "projects", "project_id"),
    ("network_intent_profiles", "topology_profile_id", "topology_profiles", "profile_id"),
    ("network_intent_profiles", "project_id", "labs", "project_id"),
    ("network_intent_profiles", "lab_id", "labs", "lab_id"),
    ("network_intent_revisions", "profile_id", "network_intent_profiles", "profile_id"),
    ("network_intent_revisions", "topology_revision_id", "topology_revisions", "revision_id"),
    ("network_intent_revisions", "parent_revision_id", "network_intent_revisions", "revision_id"),
    ("device_capability_reports", "project_id", "projects", "project_id"),
    ("device_capability_reports", "device_id", "devices", "device_id"),
    ("ansible_automation_plans", "project_id", "projects", "project_id"),
    ("ansible_automation_plans", "project_id", "labs", "project_id"),
    ("ansible_automation_plans", "lab_id", "labs", "lab_id"),
    ("ansible_automation_plans", "lab_id", "labs", "lab_id"),
    ("ansible_automation_plans", "profile_id", "network_intent_profiles", "profile_id"),
    ("ansible_automation_plans", "revision_id", "network_intent_revisions", "revision_id"),
    ("ansible_automation_approvals", "plan_id", "ansible_automation_plans", "plan_id"),
    ("ansible_automation_executions", "plan_id", "ansible_automation_plans", "plan_id"),
    ("ansible_automation_executions", "approval_id", "ansible_automation_approvals", "approval_id"),
    ("gns3_lab_bindings", "project_id", "projects", "project_id"),
    ("gns3_lab_bindings", "project_id", "labs", "project_id"),
    ("gns3_lab_bindings", "lab_id", "labs", "lab_id"),
    ("gns3_lab_bindings", "controller_device_id", "devices", "device_id"),
    ("gns3_lab_bindings", "credential_id", "managed_credentials", "credential_id"),
    ("topology_provider_mappings", "profile_id", "topology_profiles", "profile_id"),
    ("topology_provider_mappings", "project_id", "labs", "project_id"),
    ("topology_provider_mappings", "lab_id", "labs", "lab_id"),
    ("topology_apply_records", "profile_id", "topology_profiles", "profile_id"),
    ("topology_apply_records", "revision_id", "topology_revisions", "revision_id"),
    ("topology_apply_records", "project_id", "projects", "project_id"),
    ("topology_apply_records", "project_id", "labs", "project_id"),
    ("topology_apply_records", "lab_id", "labs", "lab_id"),
    ("device_configuration_deployments", "device_id", "devices", "device_id"),
    ("device_configuration_deployments", "profile_id", "configuration_profiles", "profile_id"),
    ("device_configuration_deployments", "revision_id", "configuration_revisions", "revision_id"),
    ("device_configuration_deployments", "schema_record_id", "configuration_schemas", "schema_record_id"),
    ("device_configuration_deployments", "project_id", "projects", "project_id"),
    ("device_configuration_deployments", "project_id", "labs", "project_id"),
    ("device_configuration_deployments", "lab_id", "labs", "lab_id"),
    ("performance_policy_profiles", "project_id", "projects", "project_id"),
    ("performance_policy_revisions", "policy_profile_id", "performance_policy_profiles", "policy_profile_id"),
    ("performance_policy_assignments", "project_id", "projects", "project_id"),
    ("performance_policy_assignments", "policy_profile_id", "performance_policy_profiles", "policy_profile_id"),
    ("performance_policy_assignments", "revision_id", "performance_policy_revisions", "revision_id"),
    ("labs", "project_id", "projects", "project_id"),
    ("project_memberships", "project_id", "projects", "project_id"),
    ("role_permissions", "role_id", "roles", "role_id"),
    ("role_permissions", "permission_code", "permissions", "code"),
    ("role_assignments", "role_id", "roles", "role_id"),
    ("user_sessions", "username", "users", "username"),
    ("invitation_tokens", "username", "users", "username"),
    ("password_reset_tokens", "username", "users", "username"),
    ("pipeline_definitions", "project_id", "projects", "project_id"),
    ("pipeline_definitions", "project_id", "labs", "project_id"),
    ("pipeline_definitions", "lab_id", "labs", "lab_id"),
    ("pipeline_revisions", "pipeline_id", "pipeline_definitions", "pipeline_id"),
    ("pipeline_executions", "pipeline_id", "pipeline_definitions", "pipeline_id"),
    ("pipeline_executions", "revision_id", "pipeline_revisions", "revision_id"),
    ("pipeline_executions", "project_id", "projects", "project_id"),
    ("pipeline_executions", "project_id", "labs", "project_id"),
    ("pipeline_executions", "lab_id", "labs", "lab_id"),
    ("pipeline_executions", "linked_run_id", "runs", "run_id"),
    ("pipeline_steps", "execution_id", "pipeline_executions", "execution_id"),
    ("pipeline_step_attempts", "execution_id", "pipeline_steps", "execution_id"),
    ("pipeline_step_attempts", "step_key", "pipeline_steps", "step_key"),
    ("opentofu_workspaces", "project_id", "projects", "project_id"),
    ("opentofu_workspaces", "project_id", "labs", "project_id"),
    ("opentofu_workspaces", "lab_id", "labs", "lab_id"),
    ("opentofu_plans", "workspace_id", "opentofu_workspaces", "workspace_id"),
    ("opentofu_plans", "project_id", "opentofu_workspaces", "project_id"),
    ("opentofu_plans", "lab_id", "opentofu_workspaces", "lab_id"),
    ("opentofu_approvals", "plan_id", "opentofu_plans", "plan_id"),
    ("opentofu_executions", "plan_id", "opentofu_plans", "plan_id"),
    ("infrastructure_resource_bindings", "workspace_id", "opentofu_workspaces", "workspace_id"),
    ("infrastructure_resource_bindings", "project_id", "opentofu_workspaces", "project_id"),
    ("infrastructure_resource_bindings", "lab_id", "opentofu_workspaces", "lab_id"),
    ("infrastructure_resource_bindings", "topology_profile_id", "topology_revisions", "profile_id"),
    ("infrastructure_resource_bindings", "topology_revision_id", "topology_revisions", "revision_id"),
    ("infrastructure_resource_bindings", "superseded_by", "infrastructure_resource_bindings", "binding_id"),
    ("infrastructure_reconciliations", "workspace_id", "opentofu_workspaces", "workspace_id"),
    ("infrastructure_reconciliations", "project_id", "opentofu_workspaces", "project_id"),
    ("infrastructure_reconciliations", "lab_id", "opentofu_workspaces", "lab_id"),
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
        if metadata.get("version") != "32":
            metadata_errors.append(
                f"schema_meta.version is {metadata.get('version')!r}; expected '32'"
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
