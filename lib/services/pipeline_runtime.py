"""Allow-listed handlers for durable local pipeline execution."""
from __future__ import annotations

from lib.services.configuration_deployer import ConfigurationDeploymentService
from lib.services.configuration_profile_service import ConfigurationProfileService
from lib.services.configuration_schema_registry import ConfigurationSchemaRegistry
from lib.services.topology_apply import TopologyApplyService
from lib.services.topology_studio import TopologyStudioService
from lib.services.wifi_lab_provisioning import WiFiLabProvisioningService


def build_pipeline_handlers(database, credential_vault):
    """Build the provider adapters used by a local pipeline worker."""
    schemas = ConfigurationSchemaRegistry(database)
    profiles = ConfigurationProfileService(database, schemas)
    deployer = ConfigurationDeploymentService(database, profiles, credential_vault)
    topology = TopologyStudioService(database)
    topology_apply = TopologyApplyService(database, credential_vault, topology)
    wifi = WiFiLabProvisioningService(
        database, credential_vault,
        resource_lock_manager=topology_apply.resource_lock_manager,
    )

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

    return {
        "WIFI_LAB_PROVISION": wifi_lab_provision,
        "TOPOLOGY_APPLY": topology_apply_handler,
        "PROVIDER_RECONCILE": provider_reconcile,
        "CONFIGURATION_DEPLOY": configuration_deploy,
    }
