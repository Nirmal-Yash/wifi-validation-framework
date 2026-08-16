#!/usr/bin/env python3
from __future__ import annotations
import argparse,shutil,tarfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',default=str(ROOT/'backups')); args=parser.parse_args(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True); stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'); target=out/f'netforge-{stamp}.tar.gz'
    with tarfile.open(target,'w:gz') as tar:
        for rel in ('db/results.db','config','artifacts'):
            path=ROOT/rel
            if path.exists():tar.add(path,arcname=rel)
    print(target); return 0
if __name__=='__main__':raise SystemExit(main())
