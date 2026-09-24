
# NetRegress — Business Logic and Validation Rules

## 1. Purpose

This document defines product semantics independently from implementation technology.

The test runner, database and dashboard must implement these meanings consistently.

## 2. Business entities

### Organization
Cloud customer boundary.

### Project
Firmware/product-line boundary containing validation policy, test profiles, devices, labs, baselines, Runs and evidence.

### Lab
Exclusive validation environment.

### Device
A target with identity and declared capabilities.

### Firmware
A version/build candidate and its metadata.

### Run
One validation campaign.

### Attempt
One execution attempt in a Run.

### TestResult
One logical test result.

### Metric
One numerical measurement family.

### Artifact
Evidence produced during validation.

### Baseline
Explicitly promoted known-good Run.

### ReleasePolicy
Rules for determining the business outcome of validation.

## 3. Validation profiles

Supported profiles:

- Smoke;
- Standard Regression;
- Performance;
- Full;
- Custom.

Profile selection determines the candidate test set.

Device capabilities and prerequisites further reduce the executable set.

## 4. Criticality

Every test has:

~~~text
BLOCKING
ADVISORY
INFORMATIONAL
~~~

BLOCKING failures may reject the Run.

ADVISORY failures create warnings.

INFORMATIONAL results never independently reject validation.

## 5. Severity

Every test also has:

~~~text
CRITICAL
HIGH
MEDIUM
LOW
~~~

Severity influences default criticality but does not replace project policy.

Suggested defaults:

- CRITICAL/HIGH → BLOCKING;
- MEDIUM/LOW → ADVISORY.

Projects may override the default.

## 6. Test states

Normalized states include:

~~~text
PASS
FAIL
ERROR
SKIPPED
BLOCKED
KNOWN_FAILURE
XPASS
UNVALIDATED
~~~

Raw pytest status remains available for diagnostics.

## 7. Test dependency behavior

When prerequisite A fails, test B may become BLOCKED/SKIPPED with a reason.

The platform must not intentionally execute an impossible downstream test merely to create another failure.

## 8. Test versioning

Tests are semantic assets and are versioned.

Historical Runs preserve the test definition version that produced the result.

Regression comparison across incompatible versions requires explicit human acknowledgement.

## 9. Run lifecycle

Mechanical lifecycle:

~~~text
QUEUED
PREPARING
LAB_HEALTH_CHECK
RUNNING
COMPLETED
FAILED
LAB_FAILED
CANCELLED
ABORTED
~~~

Business outcome:

~~~text
VALIDATED
VALIDATED_WITH_WARNINGS
REJECTED
UNVALIDATED
~~~

Never collapse these two dimensions.

## 10. PASS eligibility

A required test is PASS-eligible only when:

1. functional assertions pass;
2. required evidence is available;
3. required evidence validates;
4. required metrics meet policy;
5. required sample minimums are present.

## 10A. Protocol evidence

Protocol validation is based on correlated protocol events rather than packet counts.

- DHCP PASS evidence requires a correlated transaction with the expected DORA ordering.
- EAPOL authentication evidence requires an ordered four-way key exchange.
- Beacon evidence records identity and RSN/security parameters.
- DNS evidence correlates query and response transaction IDs/questions.

Missing or contradictory protocol evidence is an evidence problem and therefore may produce UNVALIDATED rather than being converted into a product failure.

## 11. Run-level VALIDATED

A Run becomes VALIDATED only when:

- all required blocking tests are valid;
- required Lab Health conditions are satisfied;
- evidence is complete;
- no blocking regression exists;
- baseline requirements are satisfied when the selected policy requires them.

## 12. VALIDATED_WITH_WARNINGS

Used when blocking criteria are satisfied but advisory issues exist.

Examples:

- advisory failures;
- allowed soft regressions;
- informational anomalies.

## 13. REJECTED

Used when product behavior is proven unacceptable according to release policy.

Examples:

- blocking functional failure;
- disallowed performance regression;
- incompatible firmware;
- explicit policy violation.

## 14. UNVALIDATED

Used when evidence or environment state prevents a trustworthy business decision.

Examples:

- lab failure;
- missing required PCAP;
- corrupt evidence;
- insufficient samples;
- failed environment snapshot;
- interrupted runner/worker.

UNVALIDATED is not a disguised product failure.

## 15. NO_BASELINE

NO_BASELINE means no comparable promoted baseline exists.

It is a regression-layer classification.

It is neither a product failure nor a Run lifecycle state.

Default CI behavior is fail-closed.

## 16. Regression dimensions

Regression dimensions are composable:

~~~text
FUNCTIONAL
PERFORMANCE
CONFIGURATION
PROTOCOL
AVAILABILITY
RECOVERY
~~~

A TestResult may contain multiple dimensions.

## 17. Regression classes

~~~text
REGRESSION
SOFT_REGRESSION
FIXED
IMPROVED
UNCHANGED
NEW_FAILURE
NEW_PASS
NO_BASELINE
UNVALIDATED
~~~

Functional result is independent of metric regression.

Example:

~~~text
functional = PASS
performance = SOFT_REGRESSION
~~~

## 18. Baseline promotion

Promotion requires:

- 100 percent of BLOCKING tests pass;
- Lab Health passes;
- minimum samples met;
- no UNVALIDATED result;
- comparable environment;
- frozen test/config definitions.

Promotion is an authorized action.

## 19. Baseline immutability

Promoted baselines are immutable.

Replacing one creates a successor and marks the old baseline superseded.

Historical baselines are retained.

## 20. Baseline comparability

Comparison considers:

- project;
- device/device family;
- hardware revision;
- firmware major line;
- test-suite version;
- environment/lab class;
- relevant configuration;
- region/band/SKU where applicable.

The system exposes an environment-similarity result rather than silently assuming equivalence.

## 21. Statistical rules

Raw samples are retained.

Warmups are diagnostic and excluded from decision statistics.

Outliers are retained.

Initial aggregate statistics:

- mean;
- median;
- minimum;
- maximum;
- p90;
- p95;
- standard deviation.

The configured aggregate is the authoritative decision metric.

## 22. Flaky tests

A test may be marked FLAKY after inconsistent outcomes occur under materially unchanged conditions.

The system never hides a failed Attempt because a later Attempt passed.

Raw history remains visible.

Project policy determines whether FLAKY blocks release.

## 23. Waivers

A waiver is an explicit exception.

Required fields:

- project;
- affected test/regression;
- firmware scope;
- reason;
- actor;
- approver;
- created time;
- optional expiration.

Waivers are audited.

Default scope is test + firmware version.

## 24. Release policy

Project example:

~~~yaml
release_policy:
  require_all_blocking_pass: true
  require_evidence_complete: true
  require_baseline: true
  allow_advisory_failures: true
  allow_soft_regressions: false
  consecutive_runs: 1
~~~

A release policy is evaluated after technical evidence exists.

## 25. Firmware lifecycle

~~~text
DRAFT
→ UNDER_VALIDATION
→ VALIDATED
→ REJECTED
→ RELEASED
→ DEPRECATED
~~~

Human approval may be required between VALIDATED and RELEASED.

## 26. Conditional tests

Executable set construction:

~~~text
project/profile
→ device capabilities
→ prerequisites
→ enabled tests
~~~

Unsupported capability means the test is not eligible.

## 27. Recovery testing

Recovery tests prove two independent events:

1. the fault caused expected disruption;
2. recovery succeeded after restoration.

Passing only the recovery half is not enough.

## 28. Automatic repair

Default:

~~~text
detect
→ preserve evidence
→ report
→ operator decides
~~~

The platform does not silently self-heal the lab and rerun.

## 29. Releasing real firmware

Firmware touching hardware requires:

- compatible device;
- validated artifact;
- checksum;
- signature where applicable;
- explicit authorization;
- audit record.

## 30. Historical immutability

Historical Runs preserve:

- original configuration;
- thresholds;
- test definitions;
- environment;
- firmware metadata;
- evidence.

Historical results are never recomputed under newer definitions.

## 31. Core business invariants

1. Required evidence failure prevents PASS.
2. Lab failure is not automatically product failure.
3. NO_BASELINE is not REGRESSION.
4. UNVALIDATED is not REJECTED.
5. Retries never erase original Attempts.
6. Baselines are immutable.
7. Waivers are explicit and audited.
8. Release rules are Project scoped.
9. Device capabilities control test applicability.
10. Technical validation and human release approval are separate decisions.
