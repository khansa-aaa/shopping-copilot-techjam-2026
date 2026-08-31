#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
DEMO_PYTHON="$REPO_ROOT/.venv-demo/bin/python"
SETUP_MARKER="$REPO_ROOT/.venv-demo/.shopping-copilot-setup"
CATALOG="$REPO_ROOT/data/catalog.jsonl"
WEB_INDEX="$REPO_ROOT/demo/web/dist/index.html"
API_LOCK="$REPO_ROOT/demo/api/requirements.lock"
WEB_LOCK="$REPO_ROOT/demo/web/package-lock.json"
EXPECTED_CATALOG_SHA256="da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67"
NEEDS_SETUP=0

fail() {
  printf 'Cannot start: %s\n' "$1" >&2
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

if [[ ! -x "$DEMO_PYTHON" || ! -f "$WEB_INDEX" || ! -f "$SETUP_MARKER" || ! -f "$API_LOCK" || ! -f "$WEB_LOCK" || ! -f "$CATALOG" ]]; then
  NEEDS_SETUP=1
elif ! "$DEMO_PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  NEEDS_SETUP=1
elif [[ "$API_LOCK" -nt "$SETUP_MARKER" || "$WEB_LOCK" -nt "$SETUP_MARKER" || "$CATALOG" -nt "$SETUP_MARKER" ]]; then
  NEEDS_SETUP=1
elif [[ -n "$(find "$REPO_ROOT/demo/web/src" "$REPO_ROOT/demo/web/public" "$REPO_ROOT/demo/web/index.html" "$REPO_ROOT/demo/web/package.json" "$REPO_ROOT/demo/web/vite.config.ts" "$REPO_ROOT/demo/web/tsconfig.json" "$REPO_ROOT/demo/web/tsconfig.app.json" "$REPO_ROOT/demo/web/tsconfig.node.json" -type f -newer "$WEB_INDEX" -print -quit)" ]]; then
  NEEDS_SETUP=1
fi

if [[ "$NEEDS_SETUP" -eq 1 ]]; then
  printf 'Local dependencies or the web build need preparation; running setup first.\n'
  "$SCRIPT_DIR/setup_local_web.sh"
fi

catalog_rows="$(wc -l < "$CATALOG" | tr -d '[:space:]')"
if [[ "$catalog_rows" != "50000" ]]; then
  fail "data/catalog.jsonl has $catalog_rows rows; expected 50000."
fi
catalog_sha256="$(sha256_file "$CATALOG")"
[[ "$catalog_sha256" == "$EXPECTED_CATALOG_SHA256" ]] \
  || fail "data/catalog.jsonl does not match the official participant-kit snapshot."

cd "$REPO_ROOT"
printf 'Starting Shopping Copilot on this Mac only.\n'
printf 'Open http://127.0.0.1:8000 after the catalog index is ready (usually about 17 seconds).\n'
printf 'Press Ctrl-C to stop. No deployment or purchase occurs.\n\n'
exec "$DEMO_PYTHON" -m demo.api
