#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$BASH_SOURCE")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="python3"
if [[ -x "$ROOT_DIR/wifi-venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/wifi-venv/bin/python"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -n "$(printenv PYTHON || true)" ]]; then
  PYTHON_BIN="$(printenv PYTHON)"
fi

if [[ -e "$ROOT_DIR/.env" || -L "$ROOT_DIR/.env" ]]; then
  if [[ -L "$ROOT_DIR/.env" || ! -f "$ROOT_DIR/.env" ]]; then
    echo "ERROR: .env must be a regular file, not a symlink." >&2
    exit 1
  fi
  ENV_MODE="$(stat -c '%a' "$ROOT_DIR/.env")"
  if (( (8#$ENV_MODE & 077) != 0 )); then
    echo "ERROR: .env must be owner-readable only (chmod 600 .env)." >&2
    exit 1
  fi
fi

read_dotenv_value() {
  if [[ ! -f "$ROOT_DIR/.env" ]]; then return 0; fi
  "$PYTHON_BIN" - "$ROOT_DIR/.env" "$1" <<'PY'
import sys
from dotenv import dotenv_values
values = dotenv_values(sys.argv[1])
value = values.get(sys.argv[2])
if value is not None:
    print(value)
PY
}

LOCAL_DIR="$ROOT_DIR/.local"
if [[ -n "$(printenv NETREGRESS_LOCAL_DIR || true)" ]]; then
  LOCAL_DIR="$(printenv NETREGRESS_LOCAL_DIR)"
else
  LOCAL_ENV_VALUE="$(read_dotenv_value NETREGRESS_LOCAL_DIR)"
  if [[ -n "$LOCAL_ENV_VALUE" ]]; then LOCAL_DIR="$LOCAL_ENV_VALUE"; fi
fi
DOTENV_NETREGRESS_PORT="$(read_dotenv_value NETREGRESS_PORT)"
DOTENV_NETREGRESS_FRONTEND_PORT="$(read_dotenv_value NETREGRESS_FRONTEND_PORT)"
DOTENV_NETREGRESS_AUTH_USERS_JSON="$(read_dotenv_value NETREGRESS_AUTH_USERS_JSON)"
AUTH_FILE="$LOCAL_DIR/netregress-auth.json"
SESSION_FILE="$LOCAL_DIR/session-secret"
MODE="start"
if [[ $# -eq 1 ]]; then MODE="$1"; fi
if [[ $# -gt 1 || ( "$MODE" != "start" && "$MODE" != "--reset-owner" ) ]]; then
  echo "Usage: $0 [--reset-owner]" >&2
  exit 2
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

load_legacy_auth_configuration() {
  export NETREGRESS_LOCAL_DIR="$LOCAL_DIR"
  export NETREGRESS_AUTH_REQUIRED=1
  if [[ -L "$AUTH_FILE" ]]; then
    log_event FAIL "Legacy authentication file must not be a symlink."
    echo "ERROR: Refusing symlinked legacy authentication file: $AUTH_FILE" >&2
    return 1
  fi
  if [[ -f "$AUTH_FILE" ]]; then
    AUTH_MODE="$(stat -c '%a' "$AUTH_FILE")"
    if (( (8#$AUTH_MODE & 077) != 0 )); then
      log_event FAIL "Legacy authentication file has unsafe permissions."
      echo "ERROR: Restrict $AUTH_FILE to owner-only access (chmod 600)." >&2
      return 1
    fi
    export NETREGRESS_AUTH_USERS_JSON="$(cat "$AUTH_FILE")"
    log_event INFO "Legacy local account hashes found; they will be imported into the persistent identity database."
  elif [[ -z "$(printenv NETREGRESS_AUTH_USERS_JSON || true)" && -n "$DOTENV_NETREGRESS_AUTH_USERS_JSON" ]]; then
    export NETREGRESS_AUTH_USERS_JSON="$DOTENV_NETREGRESS_AUTH_USERS_JSON"
    log_event INFO "Legacy environment-configured accounts will be imported into the persistent identity database."
  elif [[ -z "$(printenv NETREGRESS_AUTH_USERS_JSON || true)" ]]; then
    export NETREGRESS_AUTH_USERS_JSON=""
  fi
}

archive_legacy_auth_configuration() {
  if [[ ! -f "$AUTH_FILE" || -L "$AUTH_FILE" ]]; then return 0; fi
  "$PYTHON_BIN" - "$AUTH_FILE" <<'PY'
from pathlib import Path
import os
import sys
source = Path(sys.argv[1])
target = source.with_name(source.name + ".migrated")
suffix = 1
while target.exists():
    target = source.with_name(source.name + f".migrated-{suffix}")
    suffix += 1
os.replace(source, target)
os.chmod(target, 0o600)
print("Archived migrated legacy authentication hashes; IdentityStore is now authoritative.")
PY
  log_event PASS "Legacy authentication source archived after backend startup/migration."
}

write_session_secret() {
  "$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(32))' > "$SESSION_FILE"
  chmod 600 "$SESSION_FILE"
  log_event PASS "Session signing secret generated with restricted permissions."
}

load_legacy_auth_configuration
if [[ "$MODE" == "--reset-owner" ]]; then
  "$PYTHON_BIN" "$ROOT_DIR/scripts/netregress_owner.py"
  archive_legacy_auth_configuration
  log_event PASS "Persistent Global Owner password reset; database sessions for that account were revoked."
  echo "Global Owner password reset in the persistent identity database."
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

if ! git -C "$ROOT_DIR" ls-files --error-unmatch frontend/package-lock.json >/dev/null 2>&1 ||
   [[ ! -f "$ROOT_DIR/frontend/package-lock.json" || -L "$ROOT_DIR/frontend/package-lock.json" ]]; then
  log_event FAIL "A regular tracked frontend/package-lock.json is required."
  echo "ERROR: frontend/package-lock.json is missing, untracked, or not a regular file. Restore the committed lockfile; unlocked npm installation is disabled." >&2
  exit 1
fi
log_event PASS "Tracked frontend npm lockfile verified."

NETREGRESS_PORT="$(printenv NETREGRESS_PORT || true)"
if [[ -z "$NETREGRESS_PORT" ]]; then NETREGRESS_PORT="${DOTENV_NETREGRESS_PORT:-5050}"; fi
NETREGRESS_FRONTEND_PORT="$(printenv NETREGRESS_FRONTEND_PORT || true)"
if [[ -z "$NETREGRESS_FRONTEND_PORT" ]]; then NETREGRESS_FRONTEND_PORT="${DOTENV_NETREGRESS_FRONTEND_PORT:-5173}"; fi
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

# The source-checkout launcher binds only to loopback HTTP. A Secure cookie
# or SameSite=None without HTTPS can be silently rejected by the browser,
# leaving the user on the login page even when /auth/login returned success.
COOKIE_SECURE_VALUE="${NETREGRESS_SESSION_COOKIE_SECURE:-$(read_dotenv_value NETREGRESS_SESSION_COOKIE_SECURE)}"
COOKIE_SAMESITE_VALUE="${NETREGRESS_SESSION_COOKIE_SAMESITE:-$(read_dotenv_value NETREGRESS_SESSION_COOKIE_SAMESITE)}"
if [[ "${COOKIE_SECURE_VALUE,,}" =~ ^(1|true|yes)$ ]]; then
  log_event FAIL "Secure session cookies require an HTTPS deployment; this launcher is loopback HTTP only."
  echo "ERROR: NETREGRESS_SESSION_COOKIE_SECURE is enabled, but this launcher serves HTTP on 127.0.0.1." >&2
  echo "Unset it for local development. Use a reviewed HTTPS reverse proxy for secure-cookie deployments." >&2
  exit 1
fi
if [[ "${COOKIE_SAMESITE_VALUE,,}" == "none" ]]; then
  log_event FAIL "SameSite=None requires Secure cookies and HTTPS; this launcher is loopback HTTP only."
  echo "ERROR: NETREGRESS_SESSION_COOKIE_SAMESITE=None is incompatible with the local HTTP launcher." >&2
  echo "Use SameSite=Lax locally or run the application behind a reviewed HTTPS deployment." >&2
  exit 1
fi
export NETREGRESS_SESSION_COOKIE_SECURE=0
export NETREGRESS_SESSION_COOKIE_SAMESITE=Lax
log_event PASS "Loopback HTTP session-cookie policy validated (Secure=false, SameSite=Lax)."

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

frontend_install_fingerprint() {
  "$PYTHON_BIN" - "$ROOT_DIR/frontend/package.json" "$ROOT_DIR/frontend/package-lock.json" "$ROOT_DIR/frontend/.npmrc" "$NODE_VERSION" <<'PY'
import hashlib
import pathlib
import sys

digest = hashlib.sha256()
for raw_path in sys.argv[1:4]:
    path = pathlib.Path(raw_path)
    digest.update(path.name.encode("utf-8"))
    digest.update(bytes([0]))
    digest.update(path.read_bytes() if path.is_file() else b"<absent>")
    digest.update(bytes([0]))
digest.update(sys.argv[4].encode("ascii"))
print(digest.hexdigest())
PY
}

FRONTEND_DEPS_MARKER="$ROOT_DIR/frontend/node_modules/.netregress-install-fingerprint"
EXPECTED_FRONTEND_FINGERPRINT="$(frontend_install_fingerprint)"
INSTALLED_FRONTEND_FINGERPRINT=""
if [[ -f "$FRONTEND_DEPS_MARKER" ]]; then
  INSTALLED_FRONTEND_FINGERPRINT="$(cat "$FRONTEND_DEPS_MARKER")"
fi

if [[ ! -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ||
      "$INSTALLED_FRONTEND_FINGERPRINT" != "$EXPECTED_FRONTEND_FINGERPRINT" ]]; then
  log_event INFO "Frontend dependencies are missing or stale; installing from the committed npm lockfile."
  (cd "$ROOT_DIR/frontend" && npm ci --no-audit --no-fund --loglevel=warn)
  printf '%s\n' "$EXPECTED_FRONTEND_FINGERPRINT" > "$FRONTEND_DEPS_MARKER"
  chmod 600 "$FRONTEND_DEPS_MARKER"
  log_event PASS "Frontend dependency installation completed."
else
  log_event PASS "Frontend dependencies match package.json, .npmrc and the active Node.js runtime."
fi

if [[ -n "$NETREGRESS_AUTH_USERS_JSON" ]]; then
  log_event INFO "Legacy account configuration will be imported into the persistent database during API initialization."
else
  log_event INFO "Database-backed first-run Owner setup will be available in the browser when no account exists."
fi

if [[ ! -s "$SESSION_FILE" || $(wc -c < "$SESSION_FILE") -lt 64 ]]; then write_session_secret; fi
chmod 600 "$SESSION_FILE"
log_event PASS "Session secret file exists and permissions are restricted."

export NETREGRESS_SESSION_SECRET="$(tr -d '\r\n' < "$SESSION_FILE")"
if [[ -z "$NETREGRESS_SESSION_SECRET" ]]; then
  log_event FAIL "Session signing secret is empty."
  echo "ERROR: Local session signing secret is empty." >&2
  exit 1
fi
log_event PASS "Persistent IdentityStore authentication and session signing configuration selected."

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

SETUP_REQUIRED="$("$PYTHON_BIN" - "$NETREGRESS_PORT" <<'PY'
import json
import sys
from urllib.request import urlopen
with urlopen("http://127.0.0.1:%s/api/v1/setup/status" % int(sys.argv[1]), timeout=1) as response:
    payload = json.load(response)
    if response.status != 200 or not isinstance(payload.get("data", {}).get("first_run_required"), bool):
        raise SystemExit(1)
    print("true" if payload["data"]["first_run_required"] else "false")
PY
)" || {
  log_event FAIL "Persistent identity setup status could not be verified."
  echo "ERROR: Runner identity setup endpoint failed. Check database migration and API logs." >&2
  exit 1
}
if [[ -f "$AUTH_FILE" ]]; then
  archive_legacy_auth_configuration
fi
unset NETREGRESS_AUTH_USERS_JSON
if [[ "$SETUP_REQUIRED" == "true" ]]; then
  log_event PASS "Identity database is empty; one-time browser-based Global Owner setup is available."
else
  log_event PASS "Persistent local identity is configured; login will use database-backed accounts and RBAC."
fi

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
if [[ "$SETUP_REQUIRED" == "true" ]]; then
  echo "First run: open the dashboard and create the Global Owner account in the browser."
else
  echo "Sign in with your existing persistent local Runner account."
fi
echo "Reset an existing Global Owner password with: ./scripts/start_dashboard.sh --reset-owner."
echo "Startup verification log: $LOG_FILE"
echo "Press Ctrl+C to stop both services."
echo

wait "$FRONTEND_PID"
