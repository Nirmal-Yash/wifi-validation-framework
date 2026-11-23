# EXP-P07-A implementation audit — EVE-NG provider adapter

## Delivered

- Added an independent EVE-NG adapter under `lib/providers/eve_ng.py`; it implements the shared provider lifecycle contract and is registered alongside GNS3 and CML.
- Reuses the application-scoped ProviderRegistry, CredentialVault-backed ProviderSessionService, the existing Project/Lab binding row and the generic provider workspace identity. No duplicate topology or provider-binding data model was introduced.
- Authenticates through EVE-NG login, verifies the authenticated user and server status, and always destroys the local cookie-bearing HTTP session on disconnect.
- Restricts workspace enumeration to the authenticated user's folder; bounds recursive folder discovery; validates absolute folder paths and absolute `.unl` workspace paths; rejects path traversal, malformed paths and unsafe IDs.
- Discovers templates and their image options. A missing/stale image is never selected; a node cannot be created unless an installed image choice is exposed by the controller.
- Normalizes actual node states and discovers Ethernet and serial interfaces separately. The topology edge list is translated to actual node/network endpoints. Direct serial links are observation-only.
- Creates Ethernet links using an explicit bridge network and two interface attachments. If either attachment fails, already attached interfaces are detached best-effort and the created network is deleted best-effort. The call remains failed and is not reported as successful.
- Node create/delete/start/stop and interface/topology readback use native API operations. Packet capture and unsupported serial link mutation are not advertised.
- Updated the Lab provider selector, workspace guidance and provider-registry regression expectation.

## Verification

- `tests/test_stage_b_eve_ng.py` covers registry registration, no packet-capture claim, authenticated user/folder listing, lab creation/read-back/deletion, template/image/resource observations, Ethernet/serial interface mapping, topology edge reconstruction, bridge creation, rollback after partial attach, node lifecycle readback and path safety.
- Shared provider/topology tests continue to exercise GNS3 and CML. Hosted exact-head Stage B quality CI is required before this workstream is marked CI_VERIFIED.
- No live EVE-NG controller, licensed image, node boot, packet capture or physical provider runtime is claimed by fixture tests. Those remain separate operator acceptance evidence.
