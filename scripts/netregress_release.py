#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from lib.services.release_manifest import ReleaseManifestService
from lib.services.doctor import RunnerDoctor
def main():
    p=argparse.ArgumentParser(description="NetRegress final release integration and readiness gate");p.add_argument("mode",choices=("verify","manifest","doctor"));p.add_argument("--manifest",default="results/release-manifest.json");p.add_argument("--database");p.add_argument("--core-tests",action="store_true");a=p.parse_args()
    if a.mode=="doctor":
        r=RunnerDoctor(ROOT).run(database=a.database);print(json.dumps({"ready":r.ready,"summary":r.summary,"checks":[{"check_id":c.check_id,"status":c.status,"message":c.message} for c in r.checks]},indent=2,sort_keys=True));return 0 if r.ready else 1
    s=ReleaseManifestService(ROOT);audit=s.audit();payload=s.manifest(audit=audit)
    if a.mode=="manifest":
        d=s.write_manifest(a.manifest);print(json.dumps({"manifest":str(d),"release_ready":payload["release_ready"]},indent=2,sort_keys=True));return 0 if payload["release_ready"] else 1
    if a.core_tests:
        code=subprocess.run([sys.executable,"scripts/ci_release_gate.py"],cwd=ROOT,check=False).returncode
        if code:return code
    d=s.write_manifest(a.manifest);print(json.dumps({"manifest":str(d),"release_ready":payload["release_ready"],"branch":payload["branch"],"commit":payload["commit"],"tree":payload["tree"],"tracked_file_count":payload["tracked_file_count"]},indent=2,sort_keys=True));return 0 if payload["release_ready"] else 1
if __name__=="__main__": raise SystemExit(main())
