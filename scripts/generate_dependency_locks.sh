#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="$(command -v python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: Activate the project's Python virtual environment first." >&2
  exit 2
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)'; then
  echo "ERROR: The active Python must be a virtual environment. Activate wifi-venv first." >&2
  exit 2
fi
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: Node.js and npm are required to generate the frontend lockfile." >&2
  exit 2
fi
if [[ ! -f requirements.txt || ! -f frontend/package.json ]]; then
  echo "ERROR: Run this script from a complete NetRegress checkout." >&2
  exit 2
fi

BACKUP_DIR="$ROOT_DIR/results/backups"
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -f frontend/package-lock.json ]]; then
  BACKUP_PATH="$BACKUP_DIR/frontend-package-lock-before-$STAMP.json"
  if [[ -e "$BACKUP_PATH" ]]; then
    BACKUP_PATH="$BACKUP_DIR/frontend-package-lock-before-$STAMP-$$.json"
  fi
  cp -p -- frontend/package-lock.json "$BACKUP_PATH"
  echo "Previous frontend lock preserved at: $BACKUP_PATH"
fi
if [[ -f requirements.lock ]]; then
  BACKUP_PATH="$BACKUP_DIR/requirements-lock-before-$STAMP.txt"
  if [[ -e "$BACKUP_PATH" ]]; then
    BACKUP_PATH="$BACKUP_DIR/requirements-lock-before-$STAMP-$$.txt"
  fi
  cp -p -- requirements.lock "$BACKUP_PATH"
  echo "Previous Python lock preserved at: $BACKUP_PATH"
fi

if ! "$PYTHON_BIN" -m pip show pip-tools >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install --disable-pip-version-check pip-tools
fi
PYTHON_DIR="$("$PYTHON_BIN" -c 'import sys; print(sys.prefix)')"
PIP_COMPILE="$PYTHON_DIR/bin/pip-compile"
if [[ ! -x "$PIP_COMPILE" ]]; then
  echo "ERROR: pip-compile was not installed beside the active Python." >&2
  exit 1
fi

TEMP_LOCK="$(mktemp "$ROOT_DIR/.requirements.lock.XXXXXX")"
cleanup() { rm -f -- "$TEMP_LOCK"; }
trap cleanup EXIT

echo "Resolving hash-locked Python dependencies for minimum supported Python 3.11..."
"$PIP_COMPILE" \
  --resolver=backtracking \
  --python-version=3.11 \
  --generate-hashes \
  --allow-unsafe \
  --output-file="$TEMP_LOCK" \
  "$ROOT_DIR/requirements.txt"
mv -f -- "$TEMP_LOCK" "$ROOT_DIR/requirements.lock"
trap - EXIT

echo "Regenerating npm lockfile from frontend/package.json..."
npm --prefix "$ROOT_DIR/frontend" install \
  --package-lock-only \
  --ignore-scripts \
  --no-audit \
  --no-fund

echo "Validating Python hash lock without installing packages..."
"$PYTHON_BIN" -m pip install --dry-run --require-hashes -r "$ROOT_DIR/requirements.lock"

echo "Validating npm lockfile against the package manifest..."
node --input-type=module - "$ROOT_DIR/frontend/package.json" "$ROOT_DIR/frontend/package-lock.json" <<'NODE'
import fs from "node:fs";

const manifestPath = process.argv[2];
const lockPath = process.argv[3];
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const lock = JSON.parse(fs.readFileSync(lockPath, "utf8"));
const root = lock.packages && lock.packages[""];
let failed = false;
function fail(message) {
  console.error("ERROR:", message);
  failed = true;
}

if (!Number.isInteger(lock.lockfileVersion) || lock.lockfileVersion < 2) {
  fail("package-lock.json must use lockfileVersion 2 or newer");
}
if (!root) {
  fail("package-lock.json is missing packages[''] root metadata");
} else {
  for (const key of ["name", "version", "dependencies", "devDependencies"]) {
    const expected = JSON.stringify(manifest[key] || {});
    const observed = JSON.stringify(root[key] || {});
    if (expected !== observed) {
      fail("package-lock root " + key + " does not match package.json");
    }
  }
  for (const section of ["dependencies", "devDependencies"]) {
    for (const entry of Object.entries(manifest[section] || {})) {
      const name = entry[0];
      const version = entry[1];
      const packageEntry = lock.packages["node_modules/" + name];
      const lockedVersion = packageEntry && packageEntry.version;
      if (lockedVersion !== version) {
        fail(name + ": package.json=" + version + ", lockfile=" + (lockedVersion || "missing"));
      }
    }
  }
}
if (failed) process.exit(1);
console.log("PASS: npm lock matches " + manifest.name + "@" + manifest.version);
NODE

echo "Validating npm's clean-install contract without modifying node_modules..."
(cd "$ROOT_DIR/frontend" && npm ci --dry-run --ignore-scripts --no-audit --no-fund --loglevel=error)

echo
echo "Dependency lock generation and validation completed."
echo "Next: review requirements.lock and frontend/package-lock.json."
echo "Stage with: git add requirements.txt requirements.lock scripts/generate_dependency_locks.sh"
echo "If locally excluded: git add -f frontend/package-lock.json"
