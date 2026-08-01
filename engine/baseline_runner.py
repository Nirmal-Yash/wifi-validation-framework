import subprocess
def run_baseline(fw_version="1.0.0"):
    cmd = f"python3 -m pytest tests/ -v --fw-version={fw_version}"
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)
