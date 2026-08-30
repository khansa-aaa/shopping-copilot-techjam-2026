#!/bin/sh
set -eu

python3 -c 'import sys; assert sys.version_info >= (3, 10), sys.version'
test -f data/catalog.jsonl
test "$(wc -l < data/catalog.jsonl | tr -d ' ')" = "50000"
catalog_sha256=$(python3 -c 'import hashlib; print(hashlib.sha256(open("data/catalog.jsonl", "rb").read()).hexdigest())')
test "$catalog_sha256" = "da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67"
python3 -m compileall -q agent.py shopping_copilot starter evaluator evaluation demos tests
python3 -m unittest -v
python3 -m evaluator.local_evaluator
