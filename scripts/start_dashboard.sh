#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
LOCAL_DIR="$ROOT_DIR/.local"
AUTH_FILE="$LOCAL_DIR/netregress-auth.json"
SESSION_FILE="$LOCAL_DIR/session-secret"
MODE="${1:-start}"
if [[ $# -gt 1 || ( "$MODE" != "start" && "$MODE" != "--reset-owner" ) ]]; then
  echo "Usage: $0 [--reset-owner]" >&2
  exit 2
fi

if [[ -x "$ROOT_DIR/wifi-venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/wifi-venv/bin/python"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON:-python3}"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 || ! "$PYTHON_BIN" -c 'import flask; from lib.security import AuthManager' >/dev/null 2>&1; then
  echo "ERROR: Python dependencies are unavailable. Create/repair wifi-venv and install requirements first." >&2
  exit 1
fi

umask 077
mkdir -p "$LOCAL_DIR"
chmod 700 "$LOCAL_DIR"

prompt_owner_password() {
  if [[ ! -t 0 ]]; then
    echo "ERROR: Run this command in an interactive terminal so it can securely prompt for the owner password." >&2
    return 1
  fi
  while true; do
    read -r -s -p "Create OWNER password (at least 12 characters): " DASHBOARD_PASSWORD
    printf '\n'
    if (( ${#DASHBOARD_PASSWORD} < 12 )) || [[ ! "$DASHBOARD_PASSWORD" =~ [^[:space:]] ]]; then
      echo "Password must be at least 12 characters and contain a non-space character." >&2
      unset DASHBOARD_PASSWORD
      continue
    fi
    read -r -s -p "Confirm OWNER password: " DASHBOARD_PASSWORD_CONFIRM
    printf '\n'
    if [[ "$DASHBOARD_PASSWORD" != "$DASHBOARD_PASSWORD_CONFIRM" ]]; then
      echo "Passwords do not match. Please try again." >&2
      unset DASHBOARD_PASSWORD DASHBOARD_PASSWORD_CONFIRM
      continue
    fi
    unset DASHBOARD_PASSWORD_CONFIRM
    break
  done
}

write_owner_config() {
  prompt_owner_password
  NETREGRESS_OWNER_PASSWORD="$DASHBOARD_PASSWORD" "$PYTHON_BIN" - "$AUTH_FILE" <<'PY'
import json
import os
import sys
from lib.security import AuthManager
path = sys.argv[1]
password = os.environ["NETREGRESS_OWNER_PASSWORD"]
users = [{
    "username": "owner",
    "password_hash": AuthManager.password_hash(password),
    "role": "OWNER",
    "projects": ["*"],
}]
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(users, handle)
    handle.write("\n")
os.chmod(path, 0o600)
PY
  unset DASHBOARD_PASSWORD
}

write_session_secret() {
  "$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(32))' > "$SESSION_FILE"
  chmod 600 "$SESSION_FILE"
}

if [[ "$MODE" == "--reset-owner" ]]; then
  write_owner_config
  write_session_secret
  echo "OWNER credentials reset. Username: owner. The prior session secret was rotated."
  echo "Start the dashboard with: ./scripts/start_dashboard.sh"
  exit 0
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: Node.js and npm are required (Node.js 20.19+)." >&2
  exit 1
fi
NODE_VERSION="$(node -p 'process.versions.node')"
IFS=. read -r NODE_MAJOR NODE_MINOR NODE_PATCH <<< "$NODE_VERSION"
if (( NODE_MAJOR < 20 || ( NODE_MAJOR == 20 && NODE_MINOR < 19 ) )); then
  echo "ERROR: Node.js 20.19+ is required; detected $NODE_VERSION." >&2
  exit 1
fi

NETREGRESS_PORT="${NETREGRESS_PORT:-5000}"
if [[ ! "$NETREGRESS_PORT" =~ ^[0-9]+$ ]] || (( NETREGRESS_PORT < 1024 || NETREGRESS_PORT > 65535 )); then
  echo "ERROR: NETREGRESS_PORT must be an integer between 1024 and 65535." >&2
  exit 1
fi
export NETREGRESS_PORT
export NETREGRESS_AUTH_REQUIRED=1
export NETREGRESS_HOST="127.0.0.1"
export NETREGRESS_API_TARGET="http://127.0.0.1:${NETREGRESS_PORT}"

port_is_busy() {
  "$PYTHON_BIN" - "$1" <<'PY'
import socket
import sys
sock = socket.socket()
try:
    sock.settimeout(0.25)
    sys.exit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
finally:
    sock.close()
PY
}
if port_is_busy "$NETREGRESS_PORT"; then
  echo "ERROR: backend port $NETREGRESS_PORT is already in use." >&2
  echo "Stop the old service, or retry with NETREGRESS_PORT=5050 if that port is free." >&2
  exit 1
fi
if port_is_busy 5173; then
  echo "ERROR: frontend port 5173 is already in use. Stop the old Vite process first." >&2
  exit 1
fi

if [[ ! -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ||
      ! -f "$ROOT_DIR/frontend/node_modules/.package-lock.json" ||
      "$ROOT_DIR/frontend/package.json" -nt "$ROOT_DIR/frontend/node_modules/.package-lock.json" ||
      "$ROOT_DIR/frontend/.npmrc" -nt "$ROOT_DIR/frontend/node_modules/.package-lock.json" ]]; then
  echo "Checking/installing frontend dependencies..."
  (cd "$ROOT_DIR/frontend" && npm install)
fi

if [[ ! -f "$AUTH_FILE" ]]; then
  echo "First-time local dashboard setup."
  write_owner_config
fi
if ! "$PYTHON_BIN" - "$AUTH_FILE" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        users = json.load(handle)
except (OSError, json.JSONDecodeError):
    sys.exit(1)
valid = isinstance(users, list) and any(
    isinstance(user, dict)
    and user.get("username") == "owner"
    and user.get("role") == "OWNER"
    and isinstance(user.get("password_hash"), str)
    and bool(user["password_hash"])
    for user in users
)
sys.exit(0 if valid else 1)
PY
then
  echo "ERROR: Local auth config is invalid: $AUTH_FILE" >&2
  echo "Repair it with: ./scripts/start_dashboard.sh --reset-owner" >&2
  exit 1
fi
chmod 600 "$AUTH_FILE"
if [[ ! -s "$SESSION_FILE" || $(wc -c < "$SESSION_FILE") -lt 64 ]]; then write_session_secret; fi
chmod 600 "$SESSION_FILE"

export NETREGRESS_AUTH_USERS_JSON="$(cat "$AUTH_FILE")"
export NETREGRESS_SESSION_SECRET="$(tr -d '\r\n' < "$SESSION_FILE")"
if [[ -z "$NETREGRESS_SESSION_SECRET" || -z "$NETREGRESS_AUTH_USERS_JSON" ]]; then
  echo "ERROR: Local authentication configuration is empty." >&2
  exit 1
fi

BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$FRONTEND_PID" ]]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
  if [[ -n "$BACKEND_PID" ]]; then kill "$BACKEND_PID" 2>/dev/null || true; fi
  if [[ -n "$FRONTEND_PID" ]]; then wait "$FRONTEND_PID" 2>/dev/null || true; fi
  if [[ -n "$BACKEND_PID" ]]; then wait "$BACKEND_PID" 2>/dev/null || true; fi
  exit "$status"
}
trap cleanup EXIT INT TERM

"$PYTHON_BIN" dashboard/app.py &
BACKEND_PID=$!
BACKEND_READY=0
for attempt in $(seq 1 40); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "ERROR: Flask exited before the API became healthy. Check backend output above." >&2
    exit 1
  fi
  if "$PYTHON_BIN" - "$NETREGRESS_PORT" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import urlopen
with urlopen(f"http://127.0.0.1:{int(sys.argv[1])}/api/v1/health", timeout=0.5) as response:
    sys.exit(0 if response.status == 200 else 1)
PY
  then
    BACKEND_READY=1
    break
  fi
  sleep 0.25
done
if (( BACKEND_READY == 0 )); then
  echo "ERROR: Runner API did not become healthy on port $NETREGRESS_PORT within 10 seconds." >&2
  exit 1
fi

echo
echo "NetRegress is ready."
echo "Dashboard: http://127.0.0.1:5173"
echo "Runner API: http://127.0.0.1:${NETREGRESS_PORT}"
echo "Username: owner"
echo "Use your saved owner password; reset it with ./scripts/start_dashboard.sh --reset-owner."
echo "Press Ctrl+C to stop both services."
echo

(cd "$ROOT_DIR/frontend" && npm run start) &
FRONTEND_PID=$!
wait "$FRONTEND_PID"
