# NetRegress — Current System State

## Iterations 20–22

| Iteration | Source implementation | Runtime verification |
|---|---|---|
| 20 | Implemented: secret externalization, local authentication/RBAC, API/dashboard protection, documentation reconciliation | Pending runtime execution |
| 21 | Implemented: configuration resolver, environment fingerprint, LabController boundary, exclusive resource lock, RunOrchestrator, pytest integration | Pending runtime/integration/real-lab execution |
| 22 | Implemented: existing protocol evidence, telemetry, measurement-policy and fail-closed evidence semantics are retained and wired to the Runner lifecycle | Pending live PCAP/telemetry/performance/real-lab execution |

## Active production blockers

- Runtime execution of Iterations 20–22 in the supported Linux/GNS3/mac80211_hwsim environment.
- Iterations 23–27: device/firmware completion, frontend/persistence hardening, failure injection and final certification.
- Future Cloud/SaaS control plane.

## Verification rule

Source implementation is not runtime certification. A feature is certified only after its relevant test/integration/real-lab gate executes and produces inspectable evidence.

## Protected baseline

`436026eba597b2c6ae2e291a9cd8054b70ebbf7c`

Historical reference: 11/11 real-lab tests PASS.
