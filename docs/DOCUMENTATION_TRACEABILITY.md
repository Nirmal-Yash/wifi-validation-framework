# NetRegress — Documentation Traceability

## 1. Purpose

This document shows where the completed discovery decisions are represented in the implementation documentation.

## 2. Architecture questionnaire mapping

| Source section | Topics | Primary document | Secondary document |
|---|---|---|---|
| A | product/end-state | ARCHITECTURE_DECISIONS.md | PRD.md |
| B | Cloud/Runner execution | ARCHITECTURE_DECISIONS.md | SECURITY_AND_SAAS.md |
| C | pytest compatibility | ARCHITECTURE_DECISIONS.md | EXECUTION_AND_ADAPTERS.md |
| D | Run lifecycle | DATA_MODEL_AND_APIS.md | BUSINESS_LOGIC.md |
| E | samples/statistics | BUSINESS_LOGIC.md | IMPLEMENTATION_PLAN.md |
| F | baselines | BUSINESS_LOGIC.md | DATA_MODEL_AND_APIS.md |
| G | NO_BASELINE/UNVALIDATED | BUSINESS_LOGIC.md | IMPLEMENTATION_PLAN.md |
| H | regression | BUSINESS_LOGIC.md | DATA_MODEL_AND_APIS.md |
| I | artifacts | DATA_MODEL_AND_APIS.md | SECURITY_AND_SAAS.md |
| J | Lab Health | TECHNICAL_ARCHITECTURE.md | TESTING_AND_OPERATIONS.md |
| K | configuration | IMPLEMENTATION_PLAN.md | AGENT_CONTEXT.md |
| L | SSH/commands | EXECUTION_AND_ADAPTERS.md | SECURITY_AND_SAAS.md |
| M | device/firmware adapters | EXECUTION_AND_ADAPTERS.md | TECHNICAL_ARCHITECTURE.md |
| N | virtual/physical WiFi | BUSINESS_LOGIC.md | FRONTEND_DESIGN.md |
| O | performance | IMPLEMENTATION_PLAN.md | TESTING_AND_OPERATIONS.md |
| P | protocol evidence | EXECUTION_AND_ADAPTERS.md | IMPLEMENTATION_PLAN.md |
| Q | capture | EXECUTION_AND_ADAPTERS.md | TESTING_AND_OPERATIONS.md |
| R | frontend | FRONTEND_DESIGN.md | DATA_MODEL_AND_APIS.md |
| S | API | DATA_MODEL_AND_APIS.md | SECURITY_AND_SAAS.md |
| T | auth/RBAC | SECURITY_AND_SAAS.md | FRONTEND_DESIGN.md |
| U | Cloud queue | SECURITY_AND_SAAS.md | IMPLEMENTATION_PLAN.md |
| V | CI/webhook | SECURITY_AND_SAAS.md | DATA_MODEL_AND_APIS.md |
| W | firmware handling | EXECUTION_AND_ADAPTERS.md | SECURITY_AND_SAAS.md |
| X | database | DATA_MODEL_AND_APIS.md | IMPLEMENTATION_PLAN.md |
| Y | observability | TECHNICAL_ARCHITECTURE.md | TESTING_AND_OPERATIONS.md |
| Z | frontend migration | FRONTEND_DESIGN.md | IMPLEMENTATION_PLAN.md |
| AA | testing | TESTING_AND_OPERATIONS.md | IMPLEMENTATION_PLAN.md |
| AB | repository workflow | AGENT_CONTEXT.md | IMPLEMENTATION_PLAN.md |
| AC | provisioning shell migration | IMPLEMENTATION_PLAN.md | TECHNICAL_ARCHITECTURE.md |
| AD | operational philosophy | BUSINESS_LOGIC.md | AGENT_CONTEXT.md |
| AE | retention/deletion/export | SECURITY_AND_SAAS.md | DATA_MODEL_AND_APIS.md |
| AF | modular monolith/cloud deployment | TECHNICAL_ARCHITECTURE.md | SECURITY_AND_SAAS.md |

## 3. Business Logic mapping

| Source | Business rule document |
|---|---|
| BL-01 to BL-10 | BUSINESS_LOGIC.md sections 3–8, 16–20 |
| BL-11 to BL-16 | BUSINESS_LOGIC.md sections 8, 26, 28 |
| BL-17 to BL-20 | BUSINESS_LOGIC.md sections 7, 10, 14, 15 |
| BL-21 to BL-25 | BUSINESS_LOGIC.md sections 12, 23, 24, 25 |

## 4. Technical Clarity mapping

| Source | Technical document |
|---|---|
| TC-01 to TC-07 | TECHNICAL_ARCHITECTURE.md |
| TC-08 to TC-11 | TECHNICAL_ARCHITECTURE.md + TESTING_AND_OPERATIONS.md |
| TC-12 to TC-16 | DATA_MODEL_AND_APIS.md |
| TC-17 to TC-20 | EXECUTION_AND_ADAPTERS.md |
| TC-21 to TC-23 | TECHNICAL_ARCHITECTURE.md |
| TC-24 | IMPLEMENTATION_PLAN.md |
| TC-25 | TECHNICAL_ARCHITECTURE.md |

## 5. Document precedence

When future documents disagree:

1. Architecture decisions determine future direction.
2. Business Logic determines product semantics.
3. Technical Architecture determines internal structure.
4. Data/API documents determine persisted and external contracts.
5. Testing/Operations determines verification gates.
6. Frontend design determines presentation.
7. Existing executable code remains the current behavioral source until the relevant phase migrates it.

## 6. Open decisions

Only decisions explicitly marked deferred in the Architecture Decision Record remain intentionally open, primarily exact Cloud retention terms, final Cloud provider and final object-storage provider.

All other discovery questions have an implementation decision.

## Iteration 17 traceability

| Requirement | Implementation | Verification |
|---|---|---|
| DeviceAdapter boundary | `lib/adapters/device.py` | adapter contract tests |
| FirmwareAdapter lifecycle | `lib/adapters/firmware.py`, `lib/services/firmware_service.py` | fake lifecycle tests |
| Image integrity | SHA-256 validation + remote hash check | hash mismatch test |
| Explicit authorization | `FirmwareAuthorization` | authorization rejection test |
| Fake adapter | `lib/adapters/fake.py` | nominal/failure lifecycle tests |
| Run integration | `RunContext.device_adapter`, `RunContext.firmware_adapter` | session wiring audit |

## Iteration 18 traceability

| Requirement | Implementation | Verification |
|---|---|---|
| Fail-closed release policy | lib/services/release_gate.py | ci_tests/test_release_gate.py |
| Required test/evidence checks | ReleaseGateEvaluator | CI policy tests |
| Persisted Run evaluation | scripts/ci_release_gate.py | source audit |
| GitHub-hosted core CI | .github/workflows/internal-release-gate.yml | workflow source audit |
| Protected real-lab gate | dispatch-only self-hosted job | workflow source audit |
| Pytest node/semantic ID normalization | RegressionIntelligenceService | regression contract test |

## Iteration 19 traceability

| Requirement | Implementation | Verification |
|---|---|---|
| Durable offline queue | `SQLiteSyncQueueRepository` | queue persistence tests |
| Idempotent Run snapshot | `RunnerSyncService.queue_run` | idempotency test |
| Lease/recovery | queue claim/recover methods | expired-lease test |
| Retry semantics | `RunnerSyncService.sync_pending` | offline transport test |
| Outbound transport | `HttpSyncTransport` | source contract audit |
| Terminal Run queueing | `tests/conftest.py` | session wiring audit |