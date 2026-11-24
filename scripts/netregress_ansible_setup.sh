#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${NETREGRESS_ANSIBLE_PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python interpreter not found: $PYTHON_BIN" >&2
  exit 2
fi

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 12) or sys.version_info >= (3, 15):
    raise SystemExit(
        "P10 Ansible Core 2.21 requires Python 3.12, 3.13 or 3.14; "
        f"found {sys.version.split()[0]}"
    )
PY

# Run this after activating the same virtual environment used by NetRegress.
"$PYTHON_BIN" -m pip install --disable-pip-version-check -r requirements-ansible.txt
PYTHON_DIR="$("$PYTHON_BIN" -c 'import sys; from pathlib import Path; print(Path(sys.executable).resolve().parent)')"
export PATH="$PYTHON_DIR:$PATH"
if ! command -v ansible-galaxy >/dev/null 2>&1 || ! command -v ansible-playbook >/dev/null 2>&1; then
  echo "Ansible executables are not on PATH. Activate the NetRegress Python environment and rerun." >&2
  exit 2
fi

ansible-galaxy collection install -r ansible/requirements.yml
if ! command -v sshpass >/dev/null 2>&1; then
  echo "Note: sshpass is missing. SSH_PASSWORD execution may require: sudo apt install sshpass"
fi
ansible-playbook --version
ansible-galaxy collection list

echo "P10 Ansible runtime and pinned collections installed. This command did not connect to or change any Device."
