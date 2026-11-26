from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from lib.repositories import SQLiteDatabase
from lib.services.ansible_automation import (
    AnsibleAutomationConflict,
    AnsibleAutomationError,
    AnsibleAutomationService,
)
from lib.services.credential_vault import CredentialVaultService
from lib.services.device_inventory import DeviceInventoryService
from lib.services.network_intent import NetworkIntentService
from lib.services.network_intent_compiler import NetworkIntentCompilerService
from lib.services.resource_lock import ResourceLockManager
from lib.services.topology_studio import TopologyStudioService


class MemorySecretStore:
    def __init__(self):
        self._values = {}

    def set(self, reference: str, value: str):
        self._values[reference] = value

    def get(self, reference: str):
        return self._values.get(reference)

    def delete(self, reference: str):
        return self._values.pop(reference, None) is not None


class FakeAnsibleRunner:
    def __init__(self, device_id: str, *, validation_valid: bool = True, exit_code: int = 0):
        self.device_id = device_id
        self.validation_valid = validation_valid
        self.exit_code = exit_code
        self.execute_calls = 0

    def validate(self, *, workspace: Path, inventory: Path, playbook: Path, env):
        inventory_value = yaml.safe_load(inventory.read_text(encoding="utf-8"))
        hosts = inventory_value["all"]["children"]["netregress_targets"]["hosts"]
        assert len(hosts) == 1
        assert all("ansible_password" not in host for host in hosts.values())
        assert all("ansible_ssh_private_key_file" not in host for host in hosts.values())
        plays = yaml.safe_load(playbook.read_text(encoding="utf-8"))
        assert isinstance(plays, list) and len(plays) == 1
        assert plays[0]["tasks"]
        assert all(
            not ({"ansible.builtin.shell", "ansible.builtin.raw"} & set(task))
            for task in plays[0]["tasks"]
        )
        return {
            "valid": self.validation_valid,
            "code": "ANSIBLE_PLAYBOOK_VALIDATED" if self.validation_valid else "ANSIBLE_PLAYBOOK_SYNTAX_FAILED",
            "message": "fixture validation" if self.validation_valid else "fixture syntax failure",
            "ansible_core": "2.21.6",
            "checks": ["SYNTAX_CHECK_PASSED", "INVENTORY_CHECK_PASSED"] if self.validation_valid else [],
        }

    def execute(self, *, workspace: Path, inventory: Path, playbook: Path, env, timeout_seconds: int):
        self.execute_calls += 1
        inventory_value = yaml.safe_load(inventory.read_text(encoding="utf-8"))
        hosts = inventory_value["all"]["children"]["netregress_targets"]["hosts"]
        assert len(hosts) == 1
        host = next(iter(hosts.values()))
        assert host["ansible_password"] == "fixture-ssh-password"
        assert timeout_seconds == AnsibleAutomationService.EXECUTION_TIMEOUT_SECONDS
        if self.exit_code == 0:
            alias = next(iter(hosts))
            evidence_dir = Path(env["NETREGRESS_ANSIBLE_EVIDENCE_DIR"])
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / (alias + ".json")).write_text(
                json.dumps({"device_id": self.device_id, "verified": True}),
                encoding="utf-8",
            )
        return {
            "exit_code": self.exit_code,
            "stdout": "fixture output",
            "stderr": "fixture diagnostic",
            "timed_out": False,
        }


@pytest.fixture
def ansible_lab(tmp_path):
    database = SQLiteDatabase(tmp_path / "ansible-automation.sqlite")
    database.initialize()
    now = datetime.now(timezone.utc).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO organizations(organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("org-1", "org", "Organization", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("project-1", "org-1", "main", "Main Project", "ACTIVE", now, now),
        )
        connection.execute(
            "INSERT INTO labs(lab_id,project_id,name,provider_id,topology_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("lab-1", "project-1", "Primary Lab", "gns3", 1, "ACTIVE", now, now),
        )

    topology = TopologyStudioService(database)
    topology_profile = topology.create_profile(
        project_id="project-1", name="Primary topology",
        scope_type="LAB", scope_id="lab-1", actor="owner",
    )
    topology_revision = topology.create_revision(
        topology_profile["profile_id"],
        definition={
            "nodes": [{
                "id": "router-a", "name": "Router A", "node_type": "ROUTER",
                "template_id": "", "x": 100, "y": 100,
            }],
            "links": [],
        },
        actor="owner",
    )
    topology.publish(topology_profile["profile_id"], topology_revision["revision_id"], actor="owner")

    devices = DeviceInventoryService(database)
    device = devices.create({
        "project_id": "project-1", "lab_id": "lab-1",
        "device_key": "router-a", "name": "Router A",
        "device_type": "ROUTER", "host": "192.0.2.10", "port": 22,
        "vendor": "Cisco", "model": "IOS-XE",
    }, actor="owner")

    intent = NetworkIntentService(database, topology)
    profile = intent.create_profile(
        project_id="project-1", topology_profile_id=topology_profile["profile_id"],
        name="Primary intent", actor="owner",
    )
    definition = {
        "schema_version": "1.0",
        "targets": [{"logical_node_id": "router-a", "device_id": device["device_id"]}],
        "segments": [],
        "interfaces": [{
            "logical_node_id": "router-a", "name": "GigabitEthernet0/1",
            "admin_state": "UP", "mode": "ROUTED",
            "addresses": ["192.0.2.1/24"],
        }],
        "static_routes": [], "ospf": [], "bgp": [], "aggregations": [],
        "firewall_zones": [], "firewall_rules": [], "service_references": [],
        "linux_bridges": [], "linux_vlan_interfaces": [],
    }
    revision = intent.create_revision(
        profile["profile_id"], topology_revision_id=topology_revision["revision_id"],
        definition=definition, actor="owner",
    )
    intent.record_capability_report(
        project_id="project-1", device_id=device["device_id"],
        provider_id="gns3", platform="Cisco IOS-XE", software_version="17.12",
        adapter_name="fixture-capability-probe", adapter_version="1.0",
        capabilities={
            "addressing.ipv4": {"status": "SUPPORTED", "constraints": {}},
            "interfaces.admin_state": {"status": "SUPPORTED", "constraints": {}},
        },
        source_type="PROVIDER_ADAPTER", actor="adapter",
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    revision = intent.publish(profile["profile_id"], revision["revision_id"], actor="owner")

    secret_store = MemorySecretStore()
    vault = CredentialVaultService(database, secret_store, secret_provider="test")
    credential = vault.create(
        project_id="project-1", device_id=device["device_id"],
        label="Router SSH", credential_type="SSH_PASSWORD",
        username="netops", secret="fixture-ssh-password", actor="owner",
    )

    compiler = NetworkIntentCompilerService(database, intent, devices)
    runner = FakeAnsibleRunner(device["device_id"])
    service = AnsibleAutomationService(
        database, intent, compiler, devices, vault,
        runner=runner,
        resource_lock_manager=ResourceLockManager(tmp_path / "locks"),
    )
    return {
        "database": database, "topology": topology, "intent": intent,
        "profile": profile, "revision": revision, "device": device,
        "vault": vault, "credential": credential,
        "secret_store": secret_store, "compiler": compiler,
        "runner": runner, "service": service,
    }


def _create_plan(lab):
    return lab["service"].create_plan(
        lab["profile"]["profile_id"], lab["revision"]["revision_id"],
        credential_bindings={lab["device"]["device_id"]: lab["credential"]["credential_id"]},
        actor="owner",
    )


def test_ansible_plan_is_scoped_hash_pinned_and_contains_no_credential_material(ansible_lab):
    plan = _create_plan(ansible_lab)
    assert plan["status"] == "PREVIEWED"
    assert len(plan["plan_sha256"]) == 64
    assert plan["plan"]["project_id"] == "project-1"
    assert plan["plan"]["lab_id"] == "lab-1"
    assert plan["plan"]["intent_sha256"] == ansible_lab["revision"]["intent_sha256"]
    assert plan["plan"]["preview_contract"]["device_connection"] is False
    assert plan["plan"]["preview_contract"]["configuration_apply"] is False
    assert plan["plan"]["preview_contract"]["approval_required"] is True

    encoded = json.dumps(plan["plan"], sort_keys=True)
    assert "fixture-ssh-password" not in encoded
    assert "ansible_password" not in encoded
    assert "ansible_ssh_private_key_file" not in encoded
    assert ansible_lab["runner"].execute_calls == 0

    with ansible_lab["database"].connection() as connection:
        row = connection.execute(
            "SELECT plan_json,status FROM ansible_automation_plans WHERE plan_id=?",
            (plan["plan_id"],),
        ).fetchone()
        assert row["status"] == "PREVIEWED"
        assert "fixture-ssh-password" not in row["plan_json"]
        with pytest.raises(sqlite3.IntegrityError, match="content is immutable"):
            connection.execute(
                "UPDATE ansible_automation_plans SET plan_json='{}' WHERE plan_id=?",
                (plan["plan_id"],),
            )


def test_ansible_execution_requires_matching_explicit_approval_and_verifies_readback(ansible_lab):
    service = ansible_lab["service"]
    plan = _create_plan(ansible_lab)
    with pytest.raises(AnsibleAutomationConflict, match="must be approved"):
        service.execute(
            plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
            confirmed=True, actor="owner",
        )
    with pytest.raises(AnsibleAutomationConflict, match="hash changed"):
        service.approve(
            plan["plan_id"], expected_plan_sha256="0" * 64,
            confirmed=True, actor="owner",
        )
    with pytest.raises(AnsibleAutomationConflict, match="cannot approve their own"):
        service.approve(
            plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
            confirmed=True, actor="owner",
        )
    with pytest.raises(AnsibleAutomationConflict, match="confirmation"):
        service.approve(
            plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
            confirmed=False, actor="owner",
        )

    approved = service.approve(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
        confirmed=True, actor="approver",
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by"] == "approver"
    assert approved["approvals"][0]["plan_sha256"] == plan["plan_sha256"]

    execution = service.execute(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
        confirmed=True, actor="operator",
    )
    assert execution["status"] == "SUCCEEDED"
    assert execution["result"]["application_performed"] is True
    assert execution["result"]["readback_status"] == "VERIFIED"
    assert execution["result"]["verified_device_count"] == 1
    assert execution["result"]["reconciliation_required"] is False
    assert ansible_lab["runner"].execute_calls == 1
    final_plan = service.get_plan(plan["plan_id"])
    assert final_plan["status"] == "SUCCEEDED"
    assert final_plan["executions"][0]["status"] == "SUCCEEDED"
    assert "fixture-ssh-password" not in json.dumps(final_plan, sort_keys=True)
    with ansible_lab["database"].connection() as connection:
        credential_use = connection.execute(
            "SELECT details_json FROM audit_events WHERE action='CREDENTIAL_USED' ORDER BY occurred_at DESC LIMIT 1"
        ).fetchone()
        assert json.loads(credential_use["details_json"])["purpose"] == "ansible_automation"
        with pytest.raises(sqlite3.IntegrityError, match="result evidence is immutable"):
            connection.execute(
                "UPDATE ansible_automation_executions SET result_json='{}' WHERE execution_id=?",
                (execution["execution_id"],),
            )


def test_ansible_plan_validation_failure_is_blocked_and_cannot_be_approved(ansible_lab):
    ansible_lab["runner"].validation_valid = False
    plan = _create_plan(ansible_lab)
    assert plan["status"] == "BLOCKED"
    with pytest.raises(AnsibleAutomationConflict, match="PREVIEWED"):
        ansible_lab["service"].approve(
            plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
            confirmed=True, actor="owner",
        )


def test_stale_or_unsupported_capability_observation_invalidates_approved_plan(ansible_lab):
    service = ansible_lab["service"]
    plan = _create_plan(ansible_lab)
    service.approve(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
        confirmed=True, actor="approver",
    )
    ansible_lab["intent"].record_capability_report(
        project_id="project-1", device_id=ansible_lab["device"]["device_id"],
        provider_id="gns3", platform="Cisco IOS-XE", software_version="17.12",
        adapter_name="fixture-capability-probe", adapter_version="1.0",
        capabilities={
            "addressing.ipv4": {"status": "UNSUPPORTED", "constraints": {}},
            "interfaces.admin_state": {"status": "SUPPORTED", "constraints": {}},
        },
        source_type="PROVIDER_ADAPTER", actor="adapter",
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    with pytest.raises(AnsibleAutomationConflict, match="changed after approval"):
        service.execute(
            plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
            confirmed=True, actor="operator",
        )
    assert ansible_lab["runner"].execute_calls == 0
    assert service.get_plan(plan["plan_id"])["status"] == "STALE"


def test_ansible_nonzero_execution_records_failure_and_requires_reconciliation(ansible_lab):
    ansible_lab["runner"].exit_code = 2
    service = ansible_lab["service"]
    plan = _create_plan(ansible_lab)
    service.approve(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
        confirmed=True, actor="approver",
    )
    execution = service.execute(
        plan["plan_id"], expected_plan_sha256=plan["plan_sha256"],
        confirmed=True, actor="operator",
    )
    assert execution["status"] == "FAILED"
    assert execution["result"]["partial_changes_possible"] is True
    assert execution["result"]["readback_status"] == "INCOMPLETE"
    assert execution["result"]["reconciliation_required"] is True
    assert service.get_plan(plan["plan_id"])["status"] == "FAILED"


def test_pan_os_compiler_output_is_not_sent_through_an_unqualified_ssh_transport(ansible_lab):
    assert "paloalto_panos" not in AnsibleAutomationService.SUPPORTED_ADAPTERS
    assert "juniper_junos" in AnsibleAutomationService.SUPPORTED_ADAPTERS



def test_juniper_playbook_uses_pinned_juniper_device_modules_and_set_statements(ansible_lab):
    service = ansible_lab["service"]
    device = ansible_lab["device"]
    compilation = {
        "intent_sha256": "a" * 64,
        "artifacts": [{
            "path": f"targets/router-a-{device['device_id']}/router-a.set",
            "content": "set system host-name edge-router\nset system services ssh\n",
            "sha256": "b" * 64,
            "change_type": "CREATE",
        }],
    }
    target = {
        "device_id": device["device_id"], "lab_id": "lab-1", "device_key": "router-a",
        "name": "Router A", "host": "192.0.2.10", "port": 22,
        "vendor": "Juniper", "model": "vMX", "username": "operator",
        "credential_id": "vault-1", "credential_type": "SSH_PASSWORD",
        "adapter_id": "juniper_junos",
    }
    playbook, inventory = service._build_playbook(compilation, [target])
    host = next(iter(inventory["all"]["children"]["netregress_targets"]["hosts"].values()))
    tasks = playbook["plays"][0]["tasks"]
    assert host["ansible_connection"] == "ansible.netcommon.network_cli"
    assert host["ansible_network_os"] == "juniper.device.junos"
    config = next(task["juniper.device.junos_config"] for task in tasks if "juniper.device.junos_config" in task)
    assert config["lines"] == ["set system host-name edge-router", "set system services ssh"]
    assert config["backup"] is True
    assert any("juniper.device.junos_command" in task for task in tasks)
    assert not any("ansible.netcommon.cli_config" in task for task in tasks)
    assert not any("ansible.netcommon.cli_command" in task for task in tasks)


def test_read_only_catalog_generates_fixed_commands_and_no_configuration_modules(ansible_lab):
    service = ansible_lab["service"]
    device = ansible_lab["device"]
    compilation = {
        "intent_sha256": "c" * 64,
        "artifacts": [{
            "path": f"targets/router-a-{device['device_id']}/router-a.cfg",
            "content": "hostname router-a\\n",
            "sha256": "d" * 64,
            "change_type": "CREATE",
        }],
    }
    target = {
        "device_id": device["device_id"], "lab_id": "lab-1", "device_key": "router-a",
        "name": "Router A", "host": "192.0.2.10", "port": 22,
        "vendor": "Cisco", "model": "IOS-XE", "username": "operator",
        "credential_id": "vault-1", "credential_type": "SSH_PASSWORD",
        "adapter_id": "cisco_iosxe",
    }
    playbook, _inventory = service._build_playbook(
        compilation, [target], execution_mode="READ_ONLY",
        native_operations=("device_version", "interface_summary", "routing_summary"),
    )
    tasks = playbook["plays"][0]["tasks"]
    modules = [key for task in tasks for key in task]
    assert modules.count("ansible.netcommon.cli_command") == 3
    assert "ansible.netcommon.cli_config" not in modules
    assert "ansible.builtin.copy" in modules  # only the local evidence file
    commands = [task["ansible.netcommon.cli_command"]["command"] for task in tasks if "ansible.netcommon.cli_command" in task]
    assert commands == ["show version", "show ip interface brief", "show ip route"]
    assert playbook["targets"][0]["execution_mode"] == "READ_ONLY"


def test_read_only_plan_mode_and_operations_are_hash_pinned(ansible_lab):
    service = ansible_lab["service"]
    plan = service.create_plan(
        ansible_lab["profile"]["profile_id"], ansible_lab["revision"]["revision_id"],
        credential_bindings={ansible_lab["device"]["device_id"]: ansible_lab["credential"]["credential_id"]},
        execution_mode="READ_ONLY", native_operations=["device_version", "interface_summary"],
        actor="owner",
    )
    assert plan["status"] == "PREVIEWED"
    assert plan["plan"]["execution_mode"] == "READ_ONLY"
    assert plan["plan"]["native_operations"] == ["device_version", "interface_summary"]
    assert plan["plan"]["preview_contract"]["configuration_apply"] is False
    assert plan["plan"]["preview_contract"]["native_operations_are_read_only"] is True
    with pytest.raises(AnsibleAutomationError, match="allowlisted"):
        service.create_plan(
            ansible_lab["profile"]["profile_id"], ansible_lab["revision"]["revision_id"],
            credential_bindings={ansible_lab["device"]["device_id"]: ansible_lab["credential"]["credential_id"]},
            execution_mode="READ_ONLY", native_operations=["raw_shell"], actor="owner",
        )
    with pytest.raises(AnsibleAutomationError, match="unique"):
        service.create_plan(
            ansible_lab["profile"]["profile_id"], ansible_lab["revision"]["revision_id"],
            credential_bindings={ansible_lab["device"]["device_id"]: ansible_lab["credential"]["credential_id"]},
            execution_mode="READ_ONLY", native_operations=["device_version", "device_version"], actor="owner",
        )
