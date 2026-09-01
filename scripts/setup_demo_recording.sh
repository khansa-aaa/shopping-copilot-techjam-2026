#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
RECORDING_DIR="$REPO_ROOT/demo/recording"

fail() {
  printf 'Recording setup stopped: %s\n' "$1" >&2
  exit 1
}

command -v node >/dev/null 2>&1 || fail "Node.js is required."
command -v npm >/dev/null 2>&1 || fail "npm is required."
node -e '
  const [major, minor] = process.versions.node.split(".").map(Number);
  const supported = (major === 20 && minor >= 19) || (major === 22 && minor >= 13) || major >= 24;
  process.exit(supported ? 0 : 1);
' || fail "This locked recorder requires Node.js 20.19+, 22.13+, or 24+. Found $(node --version)."
[[ -f "$RECORDING_DIR/package-lock.json" ]] \
  || fail "demo/recording/package-lock.json is missing."

(
  cd "$RECORDING_DIR"
  npm ci
  ./node_modules/.bin/playwright install chromium
  node --input-type=module -e '
    import { accessSync } from "node:fs";
    import { chromium } from "playwright";
    accessSync(chromium.executablePath());
  '
)

printf '\nLive-demo recording dependencies are ready.\n'
