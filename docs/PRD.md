# NetRegress — Product Requirements

## 1. Product identity

NetRegress is an evidence-driven WiFi/network validation and regression platform.

This repository is the Runner/Core Validation Engine. The future NetRegress Cloud is the control plane.

Current protected laboratory baseline:

~~~text
436026eba597b2c6ae2e291a9cd8054b70ebbf7c
11 / 11 real-lab tests passing
~~~

## 2. Product vision

Move an engineer from:

firmware candidate
→ lab preparation
→ real validation
→ evidence collection
→ statistical measurement
→ baseline comparison
→ release decision

without requiring manual reconstruction of commands and evidence.

## 3. Primary users

- Validation Engineer;
- QA/Release Engineer;
- Network Engineer;
- Firmware Developer;
- Platform Operator.

## 4. Current scope

- GNS3 virtual WiFi laboratory;
- FRR/dnsmasq;
- hostapd;
- wpa_supplicant;
- mac80211_hwsim;
- DHCP;
- DNS;
- ping/loss/latency;
- iperf3;
- real packet capture;
- fault injection;
- SQLite persistence;
- firmware baselines;
- regression reporting;
- Flask dashboard;
- automated provisioning.

## 5. Target scope

- Run/Attempt evidence architecture;
- Lab Health;
- statistical validation;
- protocol evidence;
- WiFi telemetry;
- Device/Firmware adapters;
- CI release gates;
- NetRegress Runner;
- NetRegress Cloud;
- multi-tenant Projects;
- API-first dashboard;
- authenticated artifact access.

## 6. Explicit non-goals

- RF certification;
- silent autonomous repair;
- speculative Kubernetes;
- speculative microservices;
- PostgreSQL before real multi-tenant load;
- vendor-specific logic inside tests;
- synthetic packets for real validation.

## 7. Production-level workflow

Target experience:

~~~text
select firmware
→ validate image
→ select device/lab/profile
→ Lab Health
→ provision
→ Run
→ evidence
→ regression
→ policy
→ accept/reject
~~~

Manual shell work should eventually be unnecessary for the release workflow.

## 8. Core product invariant

Required evidence failure makes a validation UNVALIDATED, never PASS.

## 9. Run model

One Run contains Attempts. Each Attempt contains TestResults. TestResults contain Metrics, Samples and Artifacts.

Lifecycle and business outcome are separate axes.

## 10. Validation business outcomes

- VALIDATED;
- VALIDATED_WITH_WARNINGS;
- REJECTED;
- UNVALIDATED.

## 11. Release policy

Project-specific policies define:

- required blocking tests;
- allowed advisory failures;
- allowed soft regressions;
- baseline requirement;
- evidence requirement;
- required consecutive Runs.

## 12. Baselines

Baselines are immutable promoted Runs.

Promotion requires strong evidence, sufficient samples, passing blocking tests and healthy/comparable environment.

## 13. Regression intelligence

Regression dimensions:

- functional;
- performance;
- configuration;
- protocol;
- availability;
- recovery.

NO_BASELINE and UNVALIDATED are explicit non-regression states with different meanings.

## 14. Security requirements

Before remote exposure:

- credentials removed from tracked config;
- authentication;
- role-based authorization;
- secret redaction;
- secure artifact access;
- command safety;
- audit events.

## 15. Cloud direction

Cloud is a control plane, not the physical test executor.

Runner performs the actual lab/device validation.

Cloud owns organization/project policy, baseline promotion, waivers, release state and CI integration.

## 16. Roadmap

Phase 0: baseline protection.

Phase 1: Run, Attempt, TestResult, Metric, Sample and Artifact foundation.

Phase 1S: security gate.

Phase 2: Lab Health and lab-control extraction.

Phase 3: statistical rigor.

Phase 4: functional WiFi expansion.

Phase 5: protocol evidence.

Phase 6: WiFi telemetry.

Phase 7: regression intelligence.

Phase 8: dashboard 2.0.

Phase 9: adapters and firmware workflow.

Phase 10a: internal CI release gate.

Phase 10b: NetRegress Cloud.

Phase 11: PostgreSQL only after real concurrency.

## 17. Product acceptance philosophy

NetRegress must never improve its dashboard numbers by weakening validation.

Every result must remain traceable to:

- a Run;
- an Attempt;
- a test definition;
- a device/lab;
- an environment;
- a configuration;
- metrics/samples;
- evidence.