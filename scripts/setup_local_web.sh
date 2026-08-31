#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
DEMO_VENV="$REPO_ROOT/.venv-demo"
SETUP_MARKER="$DEMO_VENV/.shopping-copilot-setup"
CATALOG="$REPO_ROOT/data/catalog.jsonl"
CATALOG_ARCHIVE="$REPO_ROOT/data/releases/catalog.jsonl.gz"
API_LOCK="$REPO_ROOT/demo/api/requirements.lock"
WEB_DIR="$REPO_ROOT/demo/web"
EXPECTED_ROWS=50000
EXPECTED_ARCHIVE_SHA256="07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8"
EXPECTED_CATALOG_SHA256="da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67"
CATALOG_TEMP=""

cleanup() {
  if [[ -n "$CATALOG_TEMP" && -f "$CATALOG_TEMP" ]]; then
    rm -f "$CATALOG_TEMP"
  fi
}
trap cleanup EXIT

fail() {
  printf 'Setup stopped: %s\n' "$1" >&2
  exit 1
}

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    fail "shasum or sha256sum is required to verify the official catalog."
  fi
}

command -v python3 >/dev/null 2>&1 || fail "Python 3.10 or newer is required."
command -v node >/dev/null 2>&1 || fail "Node.js 20.19+, 22.13+, or 24+ is required."
command -v npm >/dev/null 2>&1 || fail "npm is required."

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "Python 3.10 or newer is required."
python3 -c 'import sqlite3; connection = sqlite3.connect(":memory:"); connection.execute("CREATE VIRTUAL TABLE probe USING fts5(value)")' \
  || fail "This Python SQLite build does not include FTS5."

node -e '
  const [major, minor] = process.versions.node.split(".").map(Number);
  const supported = (major === 20 && minor >= 19) || (major === 22 && minor >= 13) || major >= 24;
  process.exit(supported ? 0 : 1);
' || fail "This locked web build requires Node.js 20.19+, 22.13+, or 24+. Found $(node --version)."

if [[ ! -f "$CATALOG" ]]; then
  if [[ ! -f "$CATALOG_ARCHIVE" ]]; then
    fail "The official catalog is missing. Follow README.md > Get the official catalog, then rerun this script."
  fi
  archive_sha256="$(sha256_file "$CATALOG_ARCHIVE")"
  [[ "$archive_sha256" == "$EXPECTED_ARCHIVE_SHA256" ]] \
    || fail "The catalog archive checksum does not match the official participant kit."
  CATALOG_TEMP="$(mktemp "$REPO_ROOT/data/catalog.jsonl.tmp.XXXXXX")"
  gzip -dc "$CATALOG_ARCHIVE" > "$CATALOG_TEMP"
  catalog_rows="$(wc -l < "$CATALOG_TEMP" | tr -d '[:space:]')"
  [[ "$catalog_rows" == "$EXPECTED_ROWS" ]] \
    || fail "The decompressed catalog has $catalog_rows rows; expected $EXPECTED_ROWS."
  mv "$CATALOG_TEMP" "$CATALOG"
  CATALOG_TEMP=""
  printf 'Verified and unpacked the official 50,000-item catalog.\n'
fi

catalog_rows="$(wc -l < "$CATALOG" | tr -d '[:space:]')"
[[ "$catalog_rows" == "$EXPECTED_ROWS" ]] \
  || fail "data/catalog.jsonl has $catalog_rows rows; expected the official $EXPECTED_ROWS-item snapshot."
catalog_sha256="$(sha256_file "$CATALOG")"
[[ "$catalog_sha256" == "$EXPECTED_CATALOG_SHA256" ]] \
  || fail "data/catalog.jsonl does not match the official participant-kit snapshot."

[[ -f "$API_LOCK" ]] \
  || fail "demo/api/requirements.lock is missing; use the checked-in dependency lock before setup."
[[ -f "$WEB_DIR/package-lock.json" ]] \
  || fail "demo/web/package-lock.json is missing; the deterministic web install cannot continue."

if [[ ! -x "$DEMO_VENV/bin/python" ]]; then
  python3 -m venv "$DEMO_VENV"
fi

"$DEMO_VENV/bin/python" -m pip install --disable-pip-version-check \
  --require-hashes -r "$API_LOCK"

(
  cd "$WEB_DIR"
  npm ci
  npm run build
)

"$DEMO_VENV/bin/python" -c 'import fastapi, uvicorn'
[[ -f "$WEB_DIR/dist/index.html" ]] || fail "The web build did not produce demo/web/dist/index.html."
touch "$SETUP_MARKER"

printf '\nLocal web setup is ready. Start it with:\n  scripts/run_local_web.sh\n'
