# NetRegress — Release Readiness

## Purpose

Final source-of-truth checklist for the standalone Runner release wave covering Iterations 28–30.

Iterations 28–30 are one coherent release slice committed to main exactly once.

## Iteration 28 — Final Single-Commit Release Integration

- clean main working tree;
- no tracked runtime DB/PCAP/log/temp/local credential artifacts;
- all tracked Python source parses successfully;
- required release documentation and API contract exist;
- security/readiness audit and certification matrix are reproducible;
- release manifest records commit/tree/inventory/hashes;
- core release policy remains fail-closed.

Primary commands:

~~~bash
python scripts/netregress_security_audit.py --strict
python scripts/netregress_certification.py --output results/certification-matrix.json
python scripts/netregress_release.py verify
~~~

## Iteration 29 — Reproducible Operational Readiness

- RunnerDoctor reports Python/tool/path/authentication/database readiness;
- SQLite integrity is checked when a database exists;
- release inventory is content-addressed by SHA-256;
- branch/commit/tree/cleanliness are recorded;
- release CLI exposes verify/manifest/doctor modes;
- generated runtime output stays under ignored results/.

Primary commands:

~~~bash
python scripts/netregress_doctor.py
python scripts/netregress_release.py doctor
python scripts/netregress_release.py manifest
~~~

## Iteration 30 — Final Governance and Architecture Freeze

- Runner remains authoritative for execution and raw evidence;
- Cloud/SaaS remains outside the Runner release;
- fake/simulated adapters remain verification seams only;
- REAL_LAB remains an explicit certification evidence class;
- /api/v1 and existing security/release invariants are frozen;
- final architecture, roadmap, security, testing, data/API and release documents are synchronized;
- no unrelated post-freeze feature work enters this commit.

## Final release invariant

~~~text
branch = main
working_tree_clean = true
required_paths_present = true
forbidden_tracked_files = []
syntax_errors = []
release_ready = true
~~~

The manifest is structural/source-readiness evidence and never substitutes for protected GNS3/mac80211_hwsim execution evidence.
