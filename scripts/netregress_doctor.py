#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from lib.services.doctor import RunnerDoctor
p=argparse.ArgumentParser(description="NetRegress Runner environment doctor");p.add_argument("--database");a=p.parse_args();r=RunnerDoctor(ROOT).run(database=a.database)
print(json.dumps({"ready":r.ready,"summary":r.summary,"checks":[{"check_id":c.check_id,"status":c.status,"message":c.message} for c in r.checks]},indent=2,sort_keys=True));raise SystemExit(0 if r.ready else 1)
