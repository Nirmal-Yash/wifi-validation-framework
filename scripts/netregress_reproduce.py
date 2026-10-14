#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from lib.repositories import SQLiteDatabase,SQLiteRunRepository
from lib.services import ReproductionManifestService,TestRegistry

def main():
    parser=argparse.ArgumentParser(description="Create a deterministic NetRegress reproduction manifest")
    parser.add_argument("run_id")
    parser.add_argument("--database",default="results/test_results.db")
    parser.add_argument("--output",default="results/reproduction")
    args=parser.parse_args()
    database=SQLiteDatabase(args.database);database.initialize()
    run=SQLiteRunRepository(database).get(args.run_id)
    if run is None: raise SystemExit(f"Run not found: {args.run_id}")
    manifest=ReproductionManifestService(test_registry=TestRegistry.default(),root=Path(__file__).resolve().parents[1]).create(args.run_id,run,args.output)
    print(manifest.manifest_path)
if __name__=="__main__":main()
