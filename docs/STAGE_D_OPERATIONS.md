# Stage D — GNS3 Provider and Topology Apply Operations

## Delivery status

The Stage D provider/apply checkpoint is implemented in schema revision
20261115_13. The implementation extends the existing canonical topology studio;
it does not replace logical node IDs, the run topology model, or protected
capture behavior.

- P22 — GNS3 controller binding, project/template/node discovery and explicit
  node start/stop operations.
- P23 — observed link inventory, adapter/port occupancy checks and idempotent
  link creation during an explicitly confirmed topology apply.
- P24 — immutable revision hash precondition, read-only dry-run, Lab-scoped
  resource lock, partial-apply evidence and observed-versus-desired
  reconciliation.

The CI provider is mocked. A live GNS3 controller and representative template
set must still pass the operator acceptance checklist below before production
use. This document does not claim a live-controller test was performed by CI.

## Security and operating model

1. Register the GNS3 Controller as an active device in the target Project and
   Lab. Its inventory host must match the host in the provider URL.
2. Create an API_TOKEN credential for that exact controller device. The
   username is the GNS3 Basic Auth username; the secret is stored through the
   host OS secret-store adapter. SQLite and API responses contain only the
   opaque credential reference and metadata.
3. Bind one GNS3 project to the Lab through the Topology Studio. The binding is
   verified against the controller's visible project list before it is saved.
4. Use provider catalogue inspection and dry-run planning before applying.
   Planning only reads the controller; it does not create provider nodes,
   provider links or mapping records.
5. Apply requires a published revision, the exact revision SHA-256 returned by
   the plan, explicit confirmation, the topology.apply permission, and the
   Lab resource lock. Provider changes are additive. Unknown provider resources
   are reported as unmanaged and are never deleted.
6. Start and stop are separate, explicit operations. Applying a topology does
   not start every node.
7. Apply records retain the immutable revision/hash, plan, before/after
   observations, operation summary and reconciliation result. A partial failure
   is recorded and is not automatically rolled back; rerun reconciliation and
   review the apply record before retrying.

The controller URL policy accepts localhost/loopback HTTP and local/private
address HTTPS. Non-loopback private controllers require HTTPS. Public hosts,
userinfo, URL paths, queries and fragments are rejected. DNS names other than
localhost are not accepted, to avoid DNS rebinding and unexpected egress.
The HTTP client disables environment proxies and redirects, validates TLS,
uses bounded timeouts and caps response size. Error responses are sanitized;
provider response data is projected onto allow-listed fields.

## Permissions

- topology.provider.manage: verify, create/update or archive a Lab binding.
- topology.provider.operate: explicitly start or stop mapped provider nodes.
- topology.apply: apply a published topology revision to its bound Lab.
- topology.read: inspect bindings, provider catalogue, plans, apply records
  and reconciliation output.

These permissions are assigned to built-in Admin and Owner roles by the
forward-only migration. Viewer and Operator roles do not receive provider
mutation rights by default.

## Operator acceptance checklist

Before allowing a Lab to be used for live validation:

1. Upgrade the database through the normal migration manager and confirm schema
   revision 20261115_13 is clean.
2. Confirm the controller device and API_TOKEN credential are active in the
   same Project and Lab.
3. Verify the GNS3 URL host exactly matches the registered controller device.
   Use loopback HTTP only for local installations; use HTTPS for remote private
   controllers. Protect the network path with the site's VPN/firewall policy.
4. Bind the intended GNS3 project and inspect its project ID and template
   catalogue.
5. Create a small published Lab-scoped topology with one node and one link.
   Run a dry-run, inspect all planned changes, then apply with explicit
   confirmation.
6. Confirm the node and link appear in the controller, inspect the apply record
   and verify reconciliation reports IN_SYNC.
7. Test a deliberately occupied port and confirm the plan blocks without
   creating or disconnecting a link.
8. Test explicit start and stop for a disposable mapped node.
9. Simulate controller loss during an apply. Confirm the record is PARTIAL or
   FAILED, no provider resources are automatically deleted, and a later
   reconciliation can observe the surviving resources.
10. Re-run the existing protected capture, CLI and Run regression suites on the
    same Lab before enabling the integration for regular use.

## Compatibility and boundaries

- The topology canvas, profile creation and revision publishing remain
  provider-neutral local data operations.
- Logical node/link IDs remain canonical; GNS3 node/link IDs are recorded in a
  separate Project/Lab-scoped mapping table.
- A retry can recover a node created before a lost response using its
  deterministic NetRegress-managed provider name. Link retries inspect exact
  endpoint pairs and occupied ports before issuing a create request.
- Provider apply never prunes or disconnects unmanaged resources.
- Physical configuration deployment is supported only by the `openwrt.wifi.v1`
  Device-scoped adapter for registered OpenWrt Router devices. It uses a fixed
  UCI operation map, an SSH password and Wi-Fi PSK from same-device OS-vault
  credentials, strict known-host verification, a per-Device lock, explicit
  confirmation and non-secret read-back verification. Arbitrary YAML, commands,
  and unrecognized schema IDs are never translated into device commands. Other
  vendors and device families require their own reviewed adapter and tests.
- The current packaged runtime target remains Linux. A Windows build must
  validate the resource-lock backend and controller secret-store adapter on
  Windows before claiming feature parity. The existing Windows credential
  manager adapter stores the secret; the current ResourceLockManager uses
  POSIX locking and is not a Windows-compatible implementation.

## Physical-device configuration deployment

The current supported adapter is intentionally narrow:

- Schema ID/version: `openwrt.wifi.v1` v1.
- Device: active inventory record with `device_type=ROUTER` and vendor `OpenWrt`.
- Profile: published Device-scoped profile whose scope ID equals the target Device.
- Credentials: active same-Device `SSH_PASSWORD` and `WIFI_PSK` records in the OS vault.
- Transport: SSH password authentication with system known-host verification and rejection of unknown host keys. The fixed script is sent over the SSH channel's standard input; the PSK is not included in the remote process command line.
- Configuration writes are restricted to the radio country/channel, interface SSID/encryption/key and enabled flag. Only non-secret fields are read back and retained as verification evidence.
- A revision hash, explicit confirmation, per-Device lock, deployment evidence and idempotency key are required. A failed or interrupted deployment is retained as FAILED or PARTIAL and must be inspected before retry.

The adapter does not deploy general router configuration, firmware, arbitrary shell, or raw YAML. It does not claim multi-vendor coverage. Live OpenWrt hardware acceptance (known-host setup, radio section selection, regulatory-domain/channel validation and client-disconnection behavior) remains an operator release gate.

## API surface

- PUT /api/v1/labs/{lab_id}/provider-binding
- GET /api/v1/labs/{lab_id}/provider-binding
- DELETE /api/v1/labs/{lab_id}/provider-binding (archives metadata only)
- GET /api/v1/labs/{lab_id}/provider-catalog
- POST /api/v1/topologies/{profile_id}/plan
- POST /api/v1/topologies/{profile_id}/apply
- GET /api/v1/topologies/{profile_id}/reconciliation?revision_id=...
- GET /api/v1/topologies/{profile_id}/applies
- POST /api/v1/topologies/{profile_id}/nodes/{logical_node_id}/start
- POST /api/v1/topologies/{profile_id}/nodes/{logical_node_id}/stop
- POST /api/v1/configuration/profiles/{profile_id}/deploy-plan
- POST /api/v1/configuration/profiles/{profile_id}/deploy
- GET /api/v1/configuration/devices/{device_id}/deployments

All mutating endpoints continue to use the dashboard's CSRF and idempotency
controls. Binding changes, apply and node lifecycle operations serialize on the
same Lab lock. Apply history is visible in the Topology Studio and retains PARTIAL
outcomes when a controller timeout makes the result uncertain; reconcile observed
provider state before retrying an interrupted operation. API errors do not include
provider response bodies or secrets.
