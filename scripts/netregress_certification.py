#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from lib.services.certification import CertificationMatrix
def main()->int:
    parser=argparse.ArgumentParser(description="Emit/evaluate the Iteration 27 Runner certification matrix")
    parser.add_argument("--output",type=Path,default=ROOT/"results"/"certification-matrix.json")
    parser.add_argument("--evidence",type=Path)
    args=parser.parse_args()
    matrix=CertificationMatrix()
    payload=matrix.as_dict()
    payload["generated_by_commit"]=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=False).stdout.strip() or "unknown"
    if args.evidence:
        evidence=json.loads(args.evidence.read_text(encoding="utf-8"))
        missing=matrix.validate_evidence(evidence)
        payload["evidence_complete"]=not missing
        payload["missing_scenarios"]=list(missing)
    else:
        payload["evidence_complete"]=False
        payload["missing_scenarios"]=[s.scenario_id for s in matrix.scenarios]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(payload,indent=2,sort_keys=True))
    return 0 if args.evidence and payload["evidence_complete"] else 2 if args.evidence else 0
if __name__=="__main__":
    raise SystemExit(main())
