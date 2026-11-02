#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$BASH_SOURCE")/.." && pwd)"
cd "$ROOT_DIR"
umask 077

PYTHON_BIN="python3"
if [[ -x "$ROOT_DIR/wifi-venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/wifi-venv/bin/python"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -n "$(printenv PYTHON || true)" ]]; then
  PYTHON_BIN="$(printenv PYTHON)"
fi

if [[ -n "$(printenv NETREGRESS_SMOKE_ROOT || true)" ]]; then
  SMOKE_ROOT="$(printenv NETREGRESS_SMOKE_ROOT)"
  mkdir -p "$SMOKE_ROOT"
  KEEP_SMOKE_ROOT=1
else
  TEMP_ROOT="$(printenv TMPDIR || echo /tmp)"
  SMOKE_ROOT="$(mktemp -d "$TEMP_ROOT/netregress-dashboard-smoke.XXXXXX")"
  KEEP_SMOKE_ROOT=0
fi

LOCAL_DIR="$SMOKE_ROOT/local"
mkdir -p "$LOCAL_DIR/logs"
chmod 700 "$SMOKE_ROOT" "$LOCAL_DIR" "$LOCAL_DIR/logs"
VERIFY_LOG="$LOCAL_DIR/logs/dashboard-e2e-smoke-$(date -u +%Y%m%dT%H%M%SZ)-$.log"
: > "$VERIFY_LOG"
chmod 600 "$VERIFY_LOG"
exec > >(tee -a "$VERIFY_LOG") 2>&1
echo "[INFO] End-to-end dashboard smoke verification log: $VERIFY_LOG"
export NETREGRESS_LOCAL_DIR="$LOCAL_DIR"
export NETREGRESS_DATABASE_PATH="$SMOKE_ROOT/test-results.sqlite"
unset NETREGRESS_PORT NETREGRESS_FRONTEND_PORT NETREGRESS_API_TARGET

SMOKE_PASSWORD="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32))')"
NETREGRESS_SMOKE_PASSWORD="$SMOKE_PASSWORD" "$PYTHON_BIN" - "$LOCAL_DIR/netregress-auth.json" "$LOCAL_DIR/session-secret" <<'PY'
import json
import os
import secrets
import sys
from lib.security import AuthManager

auth_path, secret_path = sys.argv[1:3]
record = [{
    "username": "owner",
    "password_hash": AuthManager.password_hash(os.environ["NETREGRESS_SMOKE_PASSWORD"]),
    "role": "OWNER",
    "projects": ["*"],
}]
fd = os.open(auth_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(record, handle)
    handle.write("\n")
fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    handle.write(secrets.token_hex(32) + "\n")
os.chmod(auth_path, 0o600)
os.chmod(secret_path, 0o600)
PY

LAUNCHER_PID=""
CONSOLE_LOG="$SMOKE_ROOT/launcher-console.log"
finish() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$LAUNCHER_PID" ]]; then
    kill -TERM "$LAUNCHER_PID" 2>/dev/null || true
    wait "$LAUNCHER_PID" 2>/dev/null || true
  fi
  for port in 5050 5173; do
    if "$PYTHON_BIN" - "$port" <<'PY'
import socket
import sys
import time
port = int(sys.argv[1])
deadline = time.monotonic() + 5
while True:
    with socket.socket() as sock:
        sock.settimeout(0.1)
        listening = sock.connect_ex(("127.0.0.1", port)) == 0
    if not listening:
        sys.exit(0)
    if time.monotonic() >= deadline:
        sys.exit(1)
    time.sleep(0.1)
PY
    then
      echo "[PASS] Dashboard port $port is released after launcher shutdown."
    else
      echo "[FAIL] Dashboard child process is still listening on port $port after shutdown."
      status=1
    fi
  done
  if (( status != 0 )); then
    echo "Dashboard startup smoke test FAILED. Launcher output follows:"
    [[ -f "$CONSOLE_LOG" ]] && cat "$CONSOLE_LOG"
  fi
  if (( KEEP_SMOKE_ROOT == 1 )); then
    echo "Dashboard startup smoke artifacts: $SMOKE_ROOT"
  else
    rm -rf "$SMOKE_ROOT"
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "[INFO] Launching NetRegress with the default Flask 5050 and Vite 5173 ports."
./scripts/start_dashboard.sh >"$CONSOLE_LOG" 2>&1 &
LAUNCHER_PID=$!

READY=0
for attempt in $(seq 1 60); do
  if ! kill -0 "$LAUNCHER_PID" 2>/dev/null; then
    echo "[FAIL] Launcher exited before the API/UI became ready."
    exit 1
  fi
  if "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
from urllib.request import urlopen
with urlopen("http://127.0.0.1:5173/api/v1/health", timeout=0.5) as response:
    response.read()
    assert response.status == 200
PY
  then
    READY=1
    break
  fi
  sleep 0.25
done
if (( READY == 0 )); then
  echo "[FAIL] Dashboard did not become ready within 15 seconds."
  exit 1
fi
echo "[PASS] Real launcher startup and internal backend/frontend/proxy checks completed."

NETREGRESS_SMOKE_PASSWORD="$SMOKE_PASSWORD" "$PYTHON_BIN" - <<'PY'
import json
import os
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

base = "http://127.0.0.1:5173"
cookies = CookieJar()
client = build_opener(HTTPCookieProcessor(cookies))

def request(path, payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Accept": "*/*"}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    req = Request(base + path, data=data, headers=request_headers)
    try:
        with client.open(req, timeout=3) as response:
            raw = response.read()
            return response.status, raw, response.headers
    except HTTPError as error:
        raw = error.read()
        return error.code, raw, error.headers

status, html, _ = request("/")
assert status == 200 and b'id="root"' in html
print("[PASS] React application HTML root served by Vite.")

status, body, headers = request("/api/v1/health")
health = json.loads(body)
assert status == 200 and headers.get("Content-Type", "").startswith("application/json")
assert health.get("data", {}).get("status") == "ok"
print("[PASS] Same-origin Vite /api proxy reaches Flask /api/v1 with the canonical JSON envelope.")

status, body, _ = request("/api/v1/auth/me")
assert status == 401 and json.loads(body).get("error", {}).get("code") == "UNAUTHENTICATED"
print("[PASS] Unauthenticated session restore is rejected with HTTP 401.")

status, body, login_headers = request(
    "/api/v1/auth/login",
    {"username": "owner", "password": os.environ["NETREGRESS_SMOKE_PASSWORD"]},
)
login = json.loads(body)
assert status == 200 and login.get("data", {}).get("role") == "OWNER"
set_cookie = login_headers.get("Set-Cookie", "")
assert "HttpOnly" in set_cookie and "SameSite=Lax" in set_cookie
print("[PASS] OWNER login works through Vite and returns an HttpOnly, SameSite=Lax session cookie.")

status, body, _ = request("/api/v1/auth/csrf")
csrf = json.loads(body).get("data", {}).get("csrf_token")
assert status == 200 and isinstance(csrf, str) and csrf
print("[PASS] Authenticated CSRF token retrieval succeeds through the proxy.")

status, body, _ = request(
    "/api/v1/auth/activity",
    {},
    {"X-CSRF-Token": csrf, "Idempotency-Key": "dashboard-smoke-activity"},
)
assert status == 200 and json.loads(body).get("data", {}).get("active") is True
print("[PASS] CSRF-protected user activity heartbeat succeeds.")

status, body, _ = request(
    "/api/v1/auth/logout",
    {},
    {"X-CSRF-Token": csrf, "Idempotency-Key": "dashboard-smoke-logout"},
)
assert status == 200 and json.loads(body).get("data", {}).get("logged_out") is True
print("[PASS] CSRF-protected logout succeeds.")

status, body, _ = request("/api/v1/auth/me")
assert status == 401 and json.loads(body).get("error", {}).get("code") == "UNAUTHENTICATED"
print("[PASS] Logout invalidates the browser session; subsequent restore returns HTTP 401.")
PY

unset SMOKE_PASSWORD
echo "[PASS] End-to-end dashboard startup and session lifecycle smoke test completed."
