#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.services.certification import CertificationMatrix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit and evaluate the NetRegress 11-scenario certification matrix")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "certification-matrix.json")
    parser.add_argument("--evidence", type=Path, help="Scenario-keyed execution/evidence JSON.")
    args = parser.parse_args(argv)

    matrix = CertificationMatrix()
    payload = matrix.as_dict()
    payload["generated_by_commit"] = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        or "unknown"
    )

    if args.evidence:
        evidence_path = args.evidence.expanduser()
        if not evidence_path.is_absolute():
            evidence_path = ROOT / evidence_path
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(json.dumps({
                "status": "FAIL",
                "error": f"evidence file could not be read: {type(exc).__name__}",
            }, indent=2, sort_keys=True), file=sys.stderr)
            return 2
        if not isinstance(evidence, dict):
            parser.error("--evidence must contain a scenario-keyed JSON object")
        evaluation = matrix.evaluate_evidence(evidence, root=ROOT)
        payload.update(evaluation.as_dict())
    else:
        payload["evidence_complete"] = False
        payload["missing_scenarios"] = [scenario.scenario_id for scenario in matrix.scenarios]
        payload["issues"] = ["no execution evidence file was supplied"]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if args.evidence and payload["evidence_complete"] else 2 if args.evidence else 0


if __name__ == "__main__":
    raise SystemExit(main())
