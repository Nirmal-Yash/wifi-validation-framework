#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from lib.repositories import SQLiteDatabase
from lib.services import HttpSyncTransport, RunnerSyncService

def main() -> int:
    parser=argparse.ArgumentParser(description='Synchronize locally queued NetRegress Runner envelopes')
    parser.add_argument('--db',type=Path,default=ROOT/'results'/'test_results.db')
    parser.add_argument('--url',default=os.getenv('NETREGRESS_SYNC_URL'))
    parser.add_argument('--runner-id',default=os.getenv('NETREGRESS_RUNNER_ID') or os.getenv('HOSTNAME') or 'local-runner')
    parser.add_argument('--token',default=os.getenv('NETREGRESS_SYNC_TOKEN'))
    parser.add_argument('--limit',type=int,default=20)
    args=parser.parse_args()
    if not args.url: parser.error('--url or NETREGRESS_SYNC_URL is required')
    if not args.limit>0: parser.error('--limit must be positive')
    service=RunnerSyncService.from_sqlite(SQLiteDatabase(args.db),runner_id=args.runner_id)
    summary=service.sync_pending(HttpSyncTransport(args.url,bearer_token=args.token),limit=args.limit)
    print(json.dumps(summary,sort_keys=True))
    return 1 if summary['blocked'] else 0

if __name__=='__main__': raise SystemExit(main())