#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$BASH_SOURCE")/.." && pwd)"
cd "$ROOT_DIR"
LOCAL_DIR="$ROOT_DIR/.local"
if [[ -n "$(printenv NETREGRESS_LOCAL_DIR || true)" ]]; then LOCAL_DIR="$(printenv NETREGRESS_LOCAL_DIR)"; fi
AUTH_FILE="$LOCAL_DIR/netregress-auth.json"
SESSION_FILE="$LOCAL_DIR/session-secret"
MODE="start"
if [[ $# -eq 1 ]]; then MODE="$1"; fi
if [[ $# -gt 1 || ( "$MODE" != "start" && "$MODE" != "--reset-owner" ) ]]; then
  echo "Usage: $0 [--reset-owner]" >&2
  exit 2
fi

PYTHON_BIN="python3"
if [[ -x "$ROOT_DIR/wifi-venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/wifi-venv/bin/python"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -n "$(printenv PYTHON || true)" ]]; then
  PYTHON_BIN="$(printenv PYTHON)"
fi

umask 077
mkdir -p "$LOCAL_DIR/logs"
chmod 700 "$LOCAL_DIR" "$LOCAL_DIR/logs"
LOG_FILE="$LOCAL_DIR/logs/dashboard-startup-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
: > "$LOG_FILE"
chmod 600 "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

log_event() {
  local level="$1"
  shift
  printf '[%s] [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$level" "$*"
}

log_event INFO "Dashboard launcher started; mode=$MODE; repository=$ROOT_DIR."
log_event INFO "Private verification log: $LOG_FILE"
log_event INFO "Python executable selected: $PYTHON_BIN"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 ||
   ! "$PYTHON_BIN" -c 'import flask; from lib.security import AuthManager' >/dev/null 2>&1; then
  log_event FAIL "Python dependency check failed: Flask or AuthManager is unavailable."
  echo "ERROR: Python dependencies are unavailable. Create/repair wifi-venv and install requirements first." >&2
  exit 1
fi
log_event PASS "Python runtime, Flask and AuthManager imports verified."
log_event INFO "Python version: $("$PYTHON_BIN" --version 2>&1)"

prompt_owner_password() {
  if [[ ! -t 0 ]]; then
    log_event FAIL "OWNER setup requires an interactive terminal."
    echo "ERROR: Run this command in an interactive terminal so it can securely prompt for the owner password." >&2
    return 1
  fi
  while true; do
    read -r -s -p "Create OWNER password (at least 12 characters): " DASHBOARD_PASSWORD
    printf '\n'
    PASSWORD_LENGTH="${#DASHBOARD_PASSWORD}"
    if (( PASSWORD_LENGTH < 12 )) || [[ ! "$DASHBOARD_PASSWORD" =~ [^[:space:]] ]]; then
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
  log_event PASS "OWNER password hash saved; plaintext password was not persisted or logged."
}

write_session_secret() {
  "$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(32))' > "$SESSION_FILE"
  chmod 600 "$SESSION_FILE"
  log_event PASS "Session signing secret generated with restricted permissions."
}

if [[ "$MODE" == "--reset-owner" ]]; then
  write_owner_config
  write_session_secret
  log_event PASS "OWNER credentials reset; previous signed sessions invalidated by signing-secret rotation."
  echo "OWNER credentials reset. Username: owner. The prior session secret was rotated."
  echo "Start the dashboard with: ./scripts/start_dashboard.sh"
  exit 0
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  log_event FAIL "Node.js or npm is unavailable."
  echo "ERROR: Node.js and npm are required (Node.js 22.22.2+, 24.15+, or 26+)." >&2
  exit 1
fi

NODE_VERSION="$(node -p 'process.versions.node')"
NPM_VERSION="$(npm --version)"
if [[ ! "$NODE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  log_event FAIL "Cannot parse Node.js version string: $NODE_VERSION."
  echo "ERROR: Unable to parse Node.js version: $NODE_VERSION." >&2
  exit 1
fi
IFS=. read -r NODE_MAJOR NODE_MINOR NODE_PATCH <<< "$NODE_VERSION"
NODE_SUPPORTED=0
if (( NODE_MAJOR == 22 && ( NODE_MINOR > 22 || ( NODE_MINOR == 22 && NODE_PATCH >= 2 ) ) )); then
  NODE_SUPPORTED=1
elif (( NODE_MAJOR == 24 && NODE_MINOR >= 15 )); then
  NODE_SUPPORTED=1
elif (( NODE_MAJOR >= 26 )); then
  NODE_SUPPORTED=1
fi
log_event INFO "Node.js version=$NODE_VERSION; npm version=$NPM_VERSION."
if (( NODE_SUPPORTED == 0 )); then
  log_event FAIL "Node.js $NODE_VERSION is outside the package engine range."
  echo "ERROR: Frontend toolchain requires Node.js 22.22.2+, 24.15+, or 26+; detected $NODE_VERSION." >&2
  exit 1
fi
log_event PASS "Node.js engine compatibility verified for Vite 8 and Vitest 5."

NETREGRESS_PORT="$(printenv NETREGRESS_PORT || true)"
if [[ -z "$NETREGRESS_PORT" ]]; then NETREGRESS_PORT="5050"; fi
NETREGRESS_FRONTEND_PORT="$(printenv NETREGRESS_FRONTEND_PORT || true)"
if [[ -z "$NETREGRESS_FRONTEND_PORT" ]]; then NETREGRESS_FRONTEND_PORT="5173"; fi
for port_name in NETREGRESS_PORT NETREGRESS_FRONTEND_PORT; do
  if [[ "$port_name" == "NETREGRESS_PORT" ]]; then port_value="$NETREGRESS_PORT"; else port_value="$NETREGRESS_FRONTEND_PORT"; fi
  if [[ ! "$port_value" =~ ^[0-9]+$ ]]; then
    log_event FAIL "$port_name must be an integer port."
    echo "ERROR: $port_name must be an integer between 1024 and 65535." >&2
    exit 1
  fi
  port_number=$((10#$port_value))
  if (( port_number < 1024 || port_number > 65535 )); then
    log_event FAIL "$port_name is outside the allowed port range."
    echo "ERROR: $port_name must be an integer between 1024 and 65535." >&2
    exit 1
  fi
  if [[ "$port_name" == "NETREGRESS_PORT" ]]; then NETREGRESS_PORT="$port_number"; else NETREGRESS_FRONTEND_PORT="$port_number"; fi
done
if [[ "$NETREGRESS_PORT" == "$NETREGRESS_FRONTEND_PORT" ]]; then
  log_event FAIL "Backend and frontend ports cannot be identical."
  echo "ERROR: NETREGRESS_PORT and NETREGRESS_FRONTEND_PORT must be different." >&2
  exit 1
fi

export NETREGRESS_PORT NETREGRESS_FRONTEND_PORT
export NETREGRESS_AUTH_REQUIRED=1
export NETREGRESS_HOST="127.0.0.1"
export NETREGRESS_API_TARGET="http://127.0.0.1:$NETREGRESS_PORT"
log_event PASS "Port map validated: Flask=127.0.0.1:$NETREGRESS_PORT; Vite=127.0.0.1:$NETREGRESS_FRONTEND_PORT."
log_event INFO "Vite /api proxy target: $NETREGRESS_API_TARGET."
log_event INFO "Dashboard launcher leaves the GNS3 service port 5000 untouched."

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
  log_event FAIL "Backend port $NETREGRESS_PORT is already in use."
  echo "ERROR: backend port $NETREGRESS_PORT is already in use." >&2
  echo "Stop the old service or select another free port with NETREGRESS_PORT=5051." >&2
  exit 1
fi
log_event PASS "Backend port $NETREGRESS_PORT is available."
if port_is_busy "$NETREGRESS_FRONTEND_PORT"; then
  log_event FAIL "Frontend port $NETREGRESS_FRONTEND_PORT is already in use."
  echo "ERROR: frontend port $NETREGRESS_FRONTEND_PORT is already in use. Stop Vite or set NETREGRESS_FRONTEND_PORT=5174." >&2
  exit 1
fi
log_event PASS "Frontend port $NETREGRESS_FRONTEND_PORT is available."

if [[ ! -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ||
      ! -f "$ROOT_DIR/frontend/node_modules/.package-lock.json" ||
      "$ROOT_DIR/frontend/package.json" -nt "$ROOT_DIR/frontend/node_modules/.package-lock.json" ||
      "$ROOT_DIR/frontend/.npmrc" -nt "$ROOT_DIR/frontend/node_modules/.package-lock.json" ]]; then
  log_event INFO "Frontend dependencies are missing or stale; installing the declared dependency graph."
  (cd "$ROOT_DIR/frontend" && npm install --no-audit --no-fund --loglevel=warn)
  log_event PASS "Frontend dependency installation completed."
else
  log_event PASS "Frontend dependencies are present and current."
fi

if [[ ! -f "$AUTH_FILE" ]]; then
  log_event INFO "First-run OWNER credential setup required."
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
  log_event FAIL "Local OWNER authentication configuration is invalid."
  echo "ERROR: Local auth config is invalid: $AUTH_FILE" >&2
  echo "Repair it with: ./scripts/start_dashboard.sh --reset-owner" >&2
  exit 1
fi
chmod 600 "$AUTH_FILE"
log_event PASS "Local OWNER authentication record validated; values redacted from log."

if [[ ! -s "$SESSION_FILE" || $(wc -c < "$SESSION_FILE") -lt 64 ]]; then write_session_secret; fi
chmod 600 "$SESSION_FILE"
log_event PASS "Session secret file exists and permissions are restricted."

export NETREGRESS_AUTH_USERS_JSON="$(cat "$AUTH_FILE")"
export NETREGRESS_SESSION_SECRET="$(tr -d '\r\n' < "$SESSION_FILE")"
if [[ -z "$NETREGRESS_SESSION_SECRET" || -z "$NETREGRESS_AUTH_USERS_JSON" ]]; then
  log_event FAIL "Authentication environment or session secret is empty."
  echo "ERROR: Local authentication configuration is empty." >&2
  exit 1
fi
log_event PASS "Authentication environment loaded; secret contents intentionally omitted."

BACKEND_PID=""
FRONTEND_PID=""
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$FRONTEND_PID" ]]; then
    log_event INFO "Stopping Vite frontend process (PID $FRONTEND_PID)."
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]]; then
    log_event INFO "Stopping Flask backend process (PID $BACKEND_PID)."
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]]; then wait "$FRONTEND_PID" 2>/dev/null || true; fi
  if [[ -n "$BACKEND_PID" ]]; then wait "$BACKEND_PID" 2>/dev/null || true; fi
  log_event INFO "Launcher stopped with exit status $status."
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

log_event INFO "Starting Flask Runner API."
"$PYTHON_BIN" dashboard/app.py &
BACKEND_PID=$!
BACKEND_READY=0
for attempt in $(seq 1 40); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    log_event FAIL "Flask exited before the health endpoint became available."
    echo "ERROR: Flask exited before the API became healthy. Check backend output above." >&2
    exit 1
  fi
  if "$PYTHON_BIN" - "$NETREGRESS_PORT" <<'PY' >/dev/null 2>&1
import json
import sys
from urllib.request import urlopen
with urlopen("http://127.0.0.1:%s/api/v1/health" % int(sys.argv[1]), timeout=0.5) as response:
    payload = json.load(response)
    sys.exit(0 if response.status == 200 and payload.get("data", {}).get("status") == "ok" else 1)
PY
  then BACKEND_READY=1; break; fi
  sleep 0.25
done
if (( BACKEND_READY == 0 )); then
  log_event FAIL "Runner API did not become healthy on port $NETREGRESS_PORT within 10 seconds."
  echo "ERROR: Runner API did not become healthy on port $NETREGRESS_PORT within 10 seconds." >&2
  exit 1
fi
log_event PASS "Direct Flask GET /api/v1/health returned HTTP 200 and the expected JSON data envelope."

log_event INFO "Starting Vite React frontend."
(cd "$ROOT_DIR/frontend" && exec ./node_modules/.bin/vite --host 127.0.0.1 --port "$NETREGRESS_FRONTEND_PORT" --strictPort) &
FRONTEND_PID=$!
FRONTEND_READY=0
for attempt in $(seq 1 40); do
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    log_event FAIL "Vite exited before the React app root became available."
    echo "ERROR: Vite exited before the frontend became ready. Check frontend output above." >&2
    exit 1
  fi
  if "$PYTHON_BIN" - "$NETREGRESS_FRONTEND_PORT" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import urlopen
with urlopen("http://127.0.0.1:%s/" % int(sys.argv[1]), timeout=0.5) as response:
    html = response.read(131072).decode("utf-8", errors="replace")
    sys.exit(0 if response.status == 200 and 'id="root"' in html else 1)
PY
  then FRONTEND_READY=1; break; fi
  sleep 0.25
done
if (( FRONTEND_READY == 0 )); then
  log_event FAIL "React root was not available on port $NETREGRESS_FRONTEND_PORT within 10 seconds."
  echo "ERROR: React application did not become ready on port $NETREGRESS_FRONTEND_PORT within 10 seconds." >&2
  exit 1
fi
log_event PASS "Vite served the React application root document."

PROXY_READY=0
for attempt in $(seq 1 20); do
  if "$PYTHON_BIN" - "$NETREGRESS_FRONTEND_PORT" <<'PY' >/dev/null 2>&1
import json
import sys
from urllib.request import urlopen
with urlopen("http://127.0.0.1:%s/api/v1/health" % int(sys.argv[1]), timeout=1) as response:
    payload = json.load(response)
    sys.exit(0 if response.status == 200 and payload.get("data", {}).get("status") == "ok" else 1)
PY
  then PROXY_READY=1; break; fi
  sleep 0.25
done
if (( PROXY_READY == 0 )); then
  log_event FAIL "Vite /api proxy did not return the Flask health JSON envelope."
  echo "ERROR: Frontend API proxy check failed. Verify the proxy target and backend port." >&2
  exit 1
fi
log_event PASS "End-to-end mapping verified: Vite :$NETREGRESS_FRONTEND_PORT/api/v1/health -> Flask :$NETREGRESS_PORT/api/v1/health."
log_event PASS "All startup verification checks completed."

echo
echo "NetRegress is ready."
echo "Dashboard: http://127.0.0.1:$NETREGRESS_FRONTEND_PORT"
echo "Runner API (same-origin proxy): http://127.0.0.1:$NETREGRESS_FRONTEND_PORT/api/v1"
echo "Runner API (direct, local only): http://127.0.0.1:$NETREGRESS_PORT"
echo "Username: owner"
echo "Use your saved owner password; reset it with ./scripts/start_dashboard.sh --reset-owner."
echo "Startup verification log: $LOG_FILE"
echo "Press Ctrl+C to stop both services."
echo

wait "$FRONTEND_PID"
