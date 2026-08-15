from __future__ import annotations
import os
import subprocess
import sys


def run_baseline(fw_version='1.0.0', live=False):
    env=os.environ.copy()
    if live:
        env['NETFORGE_LIVE_TESTS']='1'
    return subprocess.run([
        sys.executable,'-m','pytest','tests','-v',f'--fw-version={fw_version}'
    ],capture_output=True,text=True,env=env,check=False)
