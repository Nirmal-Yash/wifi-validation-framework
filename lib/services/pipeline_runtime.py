"""Allow-listed handlers for durable local pipeline execution."""
from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Mapping

from lib.connector import load_devices
from lib.domain import RunLifecycle
from lib.domain.models import Metric
from lib.repositories import SQLiteAttemptRepository, SQLiteRunRepository, SQLiteTestResultRepository
from lib.services.configuration_deployer import ConfigurationDeploymentService
from lib.services.configuration_profile_service import ConfigurationProfileService
from lib.services.configuration_schema_registry import ConfigurationSchemaRegistry
from lib.services.device_inventory import DeviceInventoryService
from lib.services.performance_policy_service import PerformancePolicyService
from lib.services.pipeline_service import PipelineError, PipelineRecoveryRequired, PipelineService
from lib.services.run_process import RunProcessManager
from lib.services.test_registry import TestRegistry
from lib.services.topology_apply import TopologyApplyService
from lib.services.topology_studio import TopologyStudioService
from lib.services.wifi_lab_provisioning import WiFiLabProvisioningService


def build_pipeline_handlers(database, credential_vault, *, run_process_manager: RunProcessManager | None = None):
    """Build the provider and canonical Run adapters used by a local worker."""
    schemas = ConfigurationSchemaRegistry(database)
    profiles = ConfigurationProfileService(database, schemas)
    deployer = ConfigurationDeploymentService(database, profiles, credential_vault)
    topology = TopologyStudioService(database)
    topology_apply = TopologyApplyService(database, credential_vault, topology)
    wifi = WiFiLabProvisioningService(
        database, credential_vault,
        resource_lock_manager=topology_apply.resource_lock_manager,
        provider_registry=topology_apply.provider_registry,
        provider_session_service=topology_apply.provider_session_service,
    )
    performance_policies = PerformancePolicyService(database)
    device_inventory = DeviceInventoryService(database)
    pipeline_service = PipelineService(database)
    test_registry = TestRegistry.default()
    run_manager = run_process_manager or RunProcessManager(Path(__file__).resolve().parents[2])
    run_repository = SQLiteRunRepository(database)
    attempt_repository = SQLiteAttemptRepository(database)
    test_result_repository = SQLiteTestResultRepository(database)

    def actor(execution):
        return str(execution.get("created_by") or "pipeline-worker")

    def wifi_lab_provision(execution, step):
        item = step["definition"]["input"]
        return wifi.apply(execution["lab_id"], confirmed=item["confirmed"], actor=actor(execution))

    def topology_apply_handler(execution, step):
        item = step["definition"]["input"]
        return topology_apply.apply(
            item["profile_id"], item["revision_id"],
            expected_sha256=item["expected_sha256"], confirmed=item["confirmed"],
            actor=actor(execution),
        )

    def provider_reconcile(execution, step):
        item = step["definition"]["input"]
        return topology_apply.reconcile(item["profile_id"], item["revision_id"], actor=actor(execution))

    def configuration_deploy(execution, step):
        item = step["definition"]["input"]
        return deployer.deploy(
            item["profile_id"], item["revision_id"], device_id=item["device_id"],
            ssh_credential_id=item["ssh_credential_id"],
            wifi_psk_credential_id=item["wifi_psk_credential_id"],
            expected_sha256=item["configuration_hash"], confirmed=item["confirmed"],
            actor=actor(execution),
        )

    def resolve_run_tests(raw_tests: object) -> list[str]:
        if not isinstance(raw_tests, list) or not raw_tests:
            raise PipelineError("VALIDATION_RUN requires at least one registered test")
        resolved: list[str] = []
        for selector in raw_tests:
            if not isinstance(selector, str) or not selector.strip():
                raise PipelineError("VALIDATION_RUN test selectors must be non-empty strings")
            value = selector.strip()
            try:
                definition = test_registry.get(value)
            except KeyError:
                try:
                    definition = test_registry.resolve(value)
                except KeyError as exc:
                    raise PipelineError(
                        "VALIDATION_RUN accepts only registered semantic test IDs or registered pytest node IDs"
                    ) from exc
            if definition.node_id in resolved:
                raise PipelineError("VALIDATION_RUN test selectors resolve to duplicate pytest node IDs")
            resolved.append(definition.node_id)
        return resolved

    def validate_run_references(execution: dict, item: Mapping[str, Any]):
        project_id, lab_id = execution["project_id"], execution["lab_id"]
        with database.connection() as connection:
            scope = connection.execute(
                """SELECT l.status AS lab_status,p.status AS project_status
                   FROM labs l JOIN projects p ON p.project_id=l.project_id
                   WHERE l.lab_id=? AND l.project_id=?""",
                (lab_id, project_id),
            ).fetchone()
        if scope is None or scope["lab_status"] != "ACTIVE" or scope["project_status"] != "ACTIVE":
            raise PipelineError("VALIDATION_RUN requires the active Project and Lab pinned by its execution")

        references: dict[str, dict[str, Any]] = {}
        configuration_values: dict[str, Any] = {}
        topology_definition: dict[str, Any] = {}
        device_reference: dict[str, Any] | None = None
        managed_device_id = item.get("device_id")

        policy_revision_id = item.get("performance_policy_revision_id")
        if policy_revision_id:
            policy_revision = performance_policies.get_revision(policy_revision_id)
            if policy_revision is None or policy_revision["status"] != "PUBLISHED":
                raise PipelineError("selected performance policy revision must exist and be published")
            policy_profile = performance_policies.get_profile(policy_revision["policy_profile_id"])
            if policy_profile is None or policy_profile["project_id"] != project_id or policy_profile["status"] != "ACTIVE":
                raise PipelineError("selected performance policy revision must belong to the active Project")
            if policy_profile["scope_type"] == "LAB" and policy_profile["scope_id"] != lab_id:
                raise PipelineError("Lab-scoped performance policy does not match the pipeline Lab")
            assignment = next((
                row for row in performance_policies.list_assignments(project_id)
                if row["lab_id"] == lab_id
                and row["policy_profile_id"] == policy_profile["policy_profile_id"]
                and row["revision_id"] == policy_revision_id
            ), None)
            if assignment is None:
                raise PipelineError("selected published performance policy revision is not assigned to this Lab")
            references["performance_policy"] = {
                "revision_id": policy_revision_id,
                "sha256": policy_revision["policy_hash"],
            }

        configuration_profile_id = item.get("configuration_profile_id")
        configuration_revision_id = item.get("configuration_revision_id")
        if configuration_profile_id and configuration_revision_id:
            profile = profiles.get_profile(configuration_profile_id)
            revision = profiles.get_revision(configuration_revision_id)
            if (
                profile is None or revision is None
                or profile["project_id"] != project_id
                or revision["profile_id"] != configuration_profile_id
                or revision["status"] != "PUBLISHED"
                or profile["status"] != "PUBLISHED"
                or profile["scope_type"] not in {"PROJECT", "LAB", "DEVICE"}
                or (profile["scope_type"] == "PROJECT" and profile["scope_id"] != project_id)
                or (profile["scope_type"] == "LAB" and profile["scope_id"] != lab_id)
                or (profile["scope_type"] == "DEVICE" and profile["scope_id"] != managed_device_id)
            ):
                raise PipelineError("configuration reference must be a published revision in the same Project/Lab/Device scope")
            configuration_values = revision["values"]
            references["configuration"] = {
                "profile_id": configuration_profile_id,
                "revision_id": configuration_revision_id,
                "sha256": revision["configuration_hash"],
                "scope_type": profile["scope_type"],
                "scope_id": profile["scope_id"],
            }

        topology_profile_id = item.get("topology_profile_id")
        topology_revision_id = item.get("topology_revision_id")
        if topology_profile_id and topology_revision_id:
            profile = topology.get_profile(topology_profile_id)
            revision = topology.get_revision(topology_revision_id)
            if (
                profile is None or revision is None
                or profile["project_id"] != project_id
                or profile["lab_id"] != lab_id
                or profile["scope_type"] != "LAB"
                or revision["profile_id"] != topology_profile_id
                or revision["status"] != "PUBLISHED"
                or profile["status"] != "ACTIVE"
            ):
                raise PipelineError("topology reference must be a published Lab-scoped revision in the same Project/Lab")
            topology_definition = revision["definition"]
            references["topology"] = {
                "profile_id": topology_profile_id,
                "revision_id": topology_revision_id,
                "sha256": revision["content_sha256"],
            }

        if managed_device_id:
            device = device_inventory.get(managed_device_id)
            if (
                device is None or device["status"] != "ACTIVE"
                or device["project_id"] != project_id or device["lab_id"] != lab_id
            ):
                raise PipelineError("selected managed Device must be active in the same Project/Lab")
            device_key = device["device_key"]
            if device_key not in load_devices():
                raise PipelineError("selected Device key has no compatible Runner adapter profile in configs/devices.yaml")
            ssh_credential_id = item.get("ssh_credential_id") or device.get("credential_id")
            credential = credential_vault.get(ssh_credential_id) if ssh_credential_id else None
            if (
                credential is None or credential.get("project_id") != project_id
                or credential.get("device_id") != managed_device_id
                or credential.get("credential_type") != "SSH_PASSWORD"
                or credential.get("status") != "ACTIVE"
            ):
                raise PipelineError("selected managed Device requires an active same-device SSH_PASSWORD vault credential")
            username = credential.get("username") or device.get("username")
            if not isinstance(username, str) or not username.strip():
                raise PipelineError("selected Device SSH credential must have a username")
            device_reference = {
                "device_id": managed_device_id,
                "device_key": device_key,
                "host": device["host"],
                "port": int(device["port"]),
                "username": username.strip(),
                "ssh_credential_id": ssh_credential_id,
            }
            references["device"] = {
                "device_id": managed_device_id,
                "device_key": device_key,
                "ssh_credential_id": ssh_credential_id,
            }
        elif item.get("ssh_credential_id"):
            raise PipelineError("ssh_credential_id cannot be used without a managed device_id")

        return references, configuration_values, topology_definition, device_reference

    def aggregate_run_metrics(run_id: str) -> tuple[Metric, ...]:
        attempts = attempt_repository.list_for_run(run_id)
        if not attempts:
            return ()
        latest = max(attempts, key=lambda row: row.number)
        results = test_result_repository.list_for_attempt(latest.attempt_id)
        grouped: dict[str, dict[str, Any]] = {}
        for result in results:
            for metric in result.metrics:
                existing = grouped.get(metric.name)
                if existing is None:
                    grouped[metric.name] = {
                        "unit": metric.unit,
                        "samples": list(metric.samples),
                        "authoritative": metric.authoritative,
                    }
                    continue
                if existing["unit"] != metric.unit:
                    raise PipelineError("Run metrics with the same name use inconsistent units")
                existing["samples"].extend(metric.samples)
                existing["authoritative"] = existing["authoritative"] or metric.authoritative
        return tuple(
            Metric(name=name, unit=value["unit"], samples=tuple(value["samples"]),
                   authoritative=value["authoritative"])
            for name, value in sorted(grouped.items())
        )

    def validation_run(execution, step):
        item = step["definition"]["input"]
        pytest_nodes = resolve_run_tests(item["tests"])
        references, configuration_values, topology_definition, device_reference = validate_run_references(execution, item)
        firmware_version = str(item.get("firmware_version", "v1.0")).strip()
        if not firmware_version or len(firmware_version) > 80:
            raise PipelineError("VALIDATION_RUN firmware_version is invalid")

        environment = {
            "NETREGRESS_DATABASE_PATH": str(database.path.resolve()),
            "TEST_DB_PATH": str(database.path.resolve()),
            "NETREGRESS_PROJECT_ID": execution["project_id"],
            "NETREGRESS_LAB_ID": execution["lab_id"],
            "NETREGRESS_PIPELINE_EXECUTION_ID": execution["execution_id"],
            "NETREGRESS_PIPELINE_STEP_KEY": step["step_key"],
            "NETREGRESS_PIPELINE_REVISION_ID": execution["revision_id"],
            "NETREGRESS_PIPELINE_DEFINITION_SHA256": execution["definition_sha256"],
        }
        if "performance_policy" in references:
            environment["NETREGRESS_PERFORMANCE_POLICY_REVISION_ID"] = references["performance_policy"]["revision_id"]
            environment["NETREGRESS_PERFORMANCE_POLICY_HASH"] = references["performance_policy"]["sha256"]
        environment["NETREGRESS_RUN_REQUESTED_BY"] = actor(execution)
        if "configuration" in references:
            environment["NETREGRESS_CONFIGURATION_PROFILE_ID"] = references["configuration"]["profile_id"]
            environment["NETREGRESS_CONFIGURATION_REVISION_ID"] = references["configuration"]["revision_id"]
            environment["NETREGRESS_CONFIGURATION_HASH"] = references["configuration"]["sha256"]
            environment["NETREGRESS_CONFIGURATION_SCOPE_TYPE"] = references["configuration"]["scope_type"]
            encoded_values = json.dumps(configuration_values, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            if len(encoded_values.encode("utf-8")) > 16384:
                raise PipelineError("selected configuration values exceed the Run override size limit")
            environment["NETREGRESS_CONFIGURATION_VALUES_JSON"] = encoded_values
        if "topology" in references:
            reconciliation = topology_apply.reconcile(
                references["topology"]["profile_id"], references["topology"]["revision_id"],
                actor=actor(execution),
            )
            if reconciliation.get("status") != "IN_SYNC":
                raise PipelineError("selected topology revision is not IN_SYNC with the bound GNS3 Lab")
            references["topology"]["reconciliation_status"] = "IN_SYNC"
            encoded_topology = json.dumps(topology_definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            if len(encoded_topology.encode("utf-8")) > 32768:
                raise PipelineError("selected topology definition exceeds the Run environment limit")
            environment["NETREGRESS_TOPOLOGY_PROFILE_ID"] = references["topology"]["profile_id"]
            environment["NETREGRESS_TOPOLOGY_REVISION_ID"] = references["topology"]["revision_id"]
            environment["NETREGRESS_TOPOLOGY_HASH"] = references["topology"]["sha256"]
            environment["NETREGRESS_TOPOLOGY_DEFINITION_JSON"] = encoded_topology
        if device_reference is not None:
            environment.update({
                "NETREGRESS_DEVICE_ID": device_reference["device_key"],
                "NETREGRESS_MANAGED_DEVICE_ID": device_reference["device_id"],
                "NETREGRESS_DEVICE_HOST": device_reference["host"],
                "NETREGRESS_DEVICE_PORT": str(device_reference["port"]),
                "NETREGRESS_DEVICE_USERNAME": device_reference["username"],
                "NETREGRESS_DEVICE_SSH_CREDENTIAL_ID": device_reference["ssh_credential_id"],
            })
        current_state = pipeline_service.get_execution(execution["execution_id"])
        previous_steps = []
        for previous in (current_state or {}).get("steps", []):
            if previous["ordinal"] >= step["ordinal"] or previous["status"] != "SUCCEEDED":
                continue
            if previous["step_type"] not in {"WIFI_LAB_PROVISION", "TOPOLOGY_APPLY", "PROVIDER_RECONCILE", "CONFIGURATION_DEPLOY"}:
                continue
            source_input = previous.get("definition", {}).get("input", {})
            references_used = {
                key: value for key, value in source_input.items()
                if key.endswith("_id") or key.endswith("_hash")
            }
            source_result = previous.get("result", {})
            result_summary = {
                key: source_result[key] for key in (
                    "deployment_id", "apply_id", "status", "configuration_hash",
                    "content_sha256", "device_id", "revision_id", "profile_id",
                ) if key in source_result
            }
            previous_steps.append({
                "step_key": previous["step_key"], "step_type": previous["step_type"],
                "references": references_used, "result": result_summary,
            })
        if previous_steps:
            encoded_previous = json.dumps(previous_steps, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            if len(encoded_previous.encode("utf-8")) > 16384:
                raise PipelineError("prior pipeline step references exceed the Run environment limit")
            environment["NETREGRESS_PIPELINE_PREVIOUS_STEPS_JSON"] = encoded_previous

        handle = run_manager.start(
            tests=pytest_nodes,
            firmware_version=firmware_version,
            env=environment,
        )
        exit_code = run_manager.wait(handle.pid, timeout=float(step["timeout_seconds"]))
        if exit_code is None:
            raise PipelineRecoveryRequired(
                "validation Run exceeded its step deadline; inspect the linked Run and process log before recovery",
                details={"process_id": handle.pid, "log_path": handle.log_path},
            )

        current_execution = pipeline_service.get_execution(execution["execution_id"])
        run_id = current_execution.get("linked_run_id") if current_execution else None
        if not run_id:
            raise PipelineRecoveryRequired(
                "pytest exited without linking its canonical Run to the pipeline execution",
                details={"process_id": handle.pid, "log_path": handle.log_path, "exit_code": exit_code},
            )
        run = run_repository.get(run_id)
        if run is None:
            raise PipelineRecoveryRequired(
                "linked Run is not yet observable in the canonical Run repository",
                details={"run_id": run_id, "process_id": handle.pid},
            )
        if run.lifecycle in {RunLifecycle.QUEUED, RunLifecycle.PREPARING, RunLifecycle.LAB_HEALTH_CHECK, RunLifecycle.RUNNING}:
            raise PipelineRecoveryRequired(
                "validation process exited before its canonical Run reached a terminal state",
                details={"run_id": run_id, "process_id": handle.pid},
            )
        if run.lifecycle is not RunLifecycle.COMPLETED:
            raise PipelineError("validation Run ended in lifecycle " + run.lifecycle.value)

        performance_result = None
        if "performance_policy" in references:
            policy_revision_id = references["performance_policy"]["revision_id"]
            performance_result = performance_policies.evaluate(
                policy_revision_id, aggregate_run_metrics(run_id),
            )

        return {
            "run_id": run_id,
            "run_lifecycle": run.lifecycle.value,
            "run_outcome": run.outcome.value if run.outcome is not None else None,
            "process_exit_code": exit_code,
            "selected_tests": pytest_nodes,
            "references": references,
            "performance_policy_evaluation": performance_result,
        }

    return {
        "WIFI_LAB_PROVISION": wifi_lab_provision,
        "TOPOLOGY_APPLY": topology_apply_handler,
        "PROVIDER_RECONCILE": provider_reconcile,
        "CONFIGURATION_DEPLOY": configuration_deploy,
        "VALIDATION_RUN": validation_run,
    }
