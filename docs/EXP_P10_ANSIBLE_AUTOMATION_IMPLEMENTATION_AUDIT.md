# EXP-P10 — Ansible Automation Implementation Audit

**Status:** Implementation complete; exact-main CI verification pending  
**Scope:** P08 immutable Network Intent → P09 deterministic configuration artifacts → P10 approved Ansible execution  
**Migration:** `20261124_19` (schema version 29)  
**Service:** `lib/services/ansible_automation.py`  
**Acceptance suite:** `tests/test_ansible_automation.py`

## 1. Objective and architecture boundary

P10 is a separately governed execution layer. It does not alter the P08 canonical Network Intent schema or make the P09 compiler connect to a device. It accepts only an existing PUBLISHED Network Intent revision and obtains its configuration from `NetworkIntentCompilerService`. Ansible never receives an arbitrary user-supplied playbook, module, dynamic inventory source, connection option, shell script or command list.

The compiler output is the only source of configuration payloads. The immutable plan pins:

- Project and Lab scope, Network Intent profile and revision IDs
- P08 intent SHA-256 and canonical topology content SHA-256
- P09 compiler version, adapter descriptor and deterministic compilation identity
- Each compiled artifact path, content and SHA-256
- Generated playbook and SHA-256
- Project/Lab/Device-scoped static inventory, excluding secret material
- The selected OS Credential Vault reference for each exact target Device
- Syntax/inventory validation result, plan SHA-256 and creator identity

The plan's canonical JSON is SHA-256 verified whenever read. The generated playbook and every configuration artifact are separately re-hashed before use.

## 2. Initial execution support and deliberate exclusions

**Enabled execution transports**

| Target | Ansible transport | P10 treatment |
|---|---|---|
| Linux + FRRouting | SSH, built-in file/systemd/command modules | Generated systemd-networkd, FRR and nftables artifacts; constrained paths; non-interactive sudo for non-root users; file checksum read-back |
| Cisco IOS / IOS-XE | `ansible.netcommon.network_cli`, `cisco.ios` network OS | Generated IOS/IOS-XE CLI through `cli_config`; configuration backup; `show running-config` read-back and hostname anchor assertion |
| Arista EOS | `ansible.netcommon.network_cli`, `arista.eos` network OS | Generated EOS CLI through `cli_config`; configuration backup; `show running-config` read-back and hostname anchor assertion |

**Compile-only in P10**

Juniper Junos remains P09 compile-only until a dedicated NETCONF transport, candidate configuration, commit-check, commit/confirm and read-back semantics are separately implemented and tested. Palo Alto PAN-OS remains P09 compile-only until an authenticated, scoped and version-qualified API workflow is implemented. Neither platform is forced through the Cisco/Arista SSH module path.

The P09 adapter catalogue has five compiler targets. This does not mean all five have an Ansible execution transport.

## 3. Optional Ansible runtime and dependency controls

Ansible does not become an implicit dependency of the normal NetRegress Runner. The optional requirements are:

- Ansible Core `2.21.6`
- `ansible.netcommon 8.7.1`
- `cisco.ios 11.6.0`
- `arista.eos 12.3.0`

Install with the same activated Python environment used by the Runner:

```bash
source .venv/bin/activate
./scripts/netregress_ansible_setup.sh
ansible-playbook --version
ansible-galaxy collection list
```

P10 requires Python 3.12–3.14 for the pinned Ansible Core line. Plan validation fails closed unless the exact Core version and required collection versions are installed. It also performs an Ansible playbook syntax check and static inventory host check before a plan can reach PREVIEWED. Those checks do not open a Device connection.

Password-based SSH may require the system `sshpass` executable. Key-based SSH does not. The setup helper reports that optional system requirement instead of installing operating-system packages or silently changing the host.

## 4. Credential and inventory handling

Plan creation accepts exactly one active Credential Vault ID per target Device. Each credential must:

- belong to the same Project and exact Device
- be ACTIVE
- be SSH_PASSWORD or SSH_PRIVATE_KEY
- have an associated username

Secret values are never accepted by the API and never serialized in the plan, inventory preview, approvals, execution records or audit event details. During execution, P10 calls `CredentialVaultService.use_secret` for each reference. The callback writes the transient value to a private, mode-restricted temporary inventory or key file. The temporary workspace is removed after execution.

SSH host-key checking is explicitly enabled. There is no `StrictHostKeyChecking=no`, automatic trust-on-first-use bypass, proxy inheritance or automatic host-key installation. Operators must verify/trust the host key through their normal process before running P10. This avoids treating a successful TCP/SSH negotiation as proof of device identity.

Linux/FRR tasks use non-interactive sudo for non-root accounts. The executor does not prompt for or collect a sudo password.

## 5. Approval, RBAC and lifecycle

P10 defines:

- `network_automation.read`
- `network_automation.manage`
- `network_automation.approve`
- `network_automation.execute`

Viewer and Operator roles receive read access. Admin and Owner roles receive read/manage/approve/execute. All routes enforce the Project permission in the backend; frontend visibility is only a usability layer.

A creator cannot approve their own plan. A different authorized administrator must approve the exact 64-character plan SHA-256. Approval creates a distinct immutable row. Execution requires the same plan hash and a corresponding approval record.

```text
PREVIEWED -> APPROVED -> EXECUTING -> SUCCEEDED
                                 \-> FAILED

APPROVED -> STALE
```

STALE means the immutable source revision, topology hash, current capability observations or deterministic P09 compiler output no longer match the approved plan. The plan is not silently refreshed. It cannot execute; a fresh plan and independent approval are required.

Plan, approval and execution records have database-level scope, ownership, identity, state-transition and no-delete guards. Final execution evidence is immutable.

## 6. Execution and failure semantics

Execution repeats P09 compile/capability validation immediately before connecting to a Device, then acquires all involved Lab and Device locks. It starts one bounded Ansible subprocess with a bounded task timeout and forks set to one. This serializes target changes and stops on the first failed play.

The Linux artifact destination map is an allowlist. Vendor CLI configuration is supplied only through the network configuration adapter's generated artifact. P10 then performs a minimal read-back assertion:

- Linux/FRR: SHA-256 checksums for every deployed file
- IOS/IOS-XE and EOS: running-config contains the expected generated hostname anchor

This is an initial read-back integrity signal, not full configuration-state drift reconciliation. Ansible task `no_log` is enabled for sensitive file writes and device configuration tasks; subprocess summaries are redacted against the resolved secrets before persistence.

Multi-device execution is **not atomic**. If an earlier Device changed and a later Device fails, those prior changes are not automatically rolled back. The execution is FAILED, partial changes are possible, read-back is incomplete and reconciliation is required. P10 does not automatically retry. It does not claim that an earlier Device is restored to its previous configuration.

The current API executes synchronously with a strict bounded timeout. Long-running enterprise deployment orchestration, resumable controller jobs, background worker leases, per-host continuation, approval separation by organizational change window, automatic rollback and full drift reconciliation are subsequent engineering work.

## 7. API surface

| Endpoint | Purpose | Permission |
|---|---|---|
| `GET /api/v1/network-intent/automation/ansible/plans?project_id=...` | Project-scoped plan history | `network_automation.read` |
| `GET /api/v1/network-intent/automation/ansible/plans/{plan_id}` | Hash-verified plan and evidence | `network_automation.read` |
| `POST /api/v1/network-intent/profiles/{profile_id}/revisions/{revision_id}/ansible-plan` | Build and validate plan from a published revision | `network_automation.manage` |
| `POST /api/v1/network-intent/automation/ansible/plans/{plan_id}/approve` | Independent approval of exact plan hash | `network_automation.approve` |
| `POST /api/v1/network-intent/automation/ansible/plans/{plan_id}/execute` | Explicit execution of the approved hash | `network_automation.execute` |

POST routes follow the existing session, CSRF, idempotency and audit conventions.

## 8. Database and audit controls

Migration `20261124_19` adds:

- `ansible_automation_plans`
- `ansible_automation_approvals`
- `ansible_automation_executions`

The new tables include Project/Lab and immutable Network Intent foreign keys, SHA-256 checks, bounded JSON storage, state checks, audit identity and indexes. Triggers reject cross-scope plan creation, mismatched plan/approval/execution hashes, invalid lifecycle transitions, edits to plan identity/content, changes to approval identity, edits to final execution results and all deletes. Schema version 29 and the runtime schema contract are updated.

## 9. Automated verification

`tests/test_ansible_automation.py` uses a fake Ansible runner and in-memory secret store. It covers:

- published revision and scoped target plan creation
- generated playbook and static inventory shape
- absence of credential material from the stored plan
- syntax/inventory validation blocking
- hash mismatch and explicit confirmation requirements
- creator self-approval rejection and independent approval
- approved execution and per-device read-back evidence
- capability drift after approval, plan STALE transition and zero Device executions
- non-zero Ansible result, possible partial changes and reconciliation requirement
- Junos/PAN-OS execution transport exclusion
- immutable execution-result persistence

The P10 module is included in the hosted quality workflow and the frozen desktop backend smoke-contract module set.

Automated fixture results are software-contract evidence only. They do not certify a live SSH session, switch/router configuration syntax, successful network convergence, service restoration, failover, real command output, platform licensing, hardware state or rollback safety.

## 10. Remaining acceptance gates

Before a first live change, an operator must verify the Device identity/SSH host key, target software version, SSH privileges, Linux sudo policy, required installed Ansible collections and the organization's change approval. Run first against a disposable lab and inspect the generated playbook, exact plan hash and execution read-back. Protect the resulting evidence and reconcile any FAILED/STALE plan before a new attempt.

Junos NETCONF, PAN-OS API, full running-configuration diff, post-apply protocol/route/ACL verification, true multi-device transaction compensation, resumable execution workers, and external representative-device acceptance remain outside this P10 v1.0 implementation.
