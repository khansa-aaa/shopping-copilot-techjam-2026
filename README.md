# Shopping Copilot — TechJam 2026

Submission-ready, headless conversational product retrieval agent for the
TechJam Conversational E-Commerce Search Challenge. The official 50,000-item
catalog and ten-turn/exact-`parent_asin` protocol are unchanged. No UI or hosted
service is required.

The default configuration is fully offline and uses only Python's standard
library. It achieved the following result with the unmodified public evaluator:

| Metric | Official weak baseline | Shopping Copilot |
|---|---:|---:|
| HitRate@10 | 0.125 | **0.985** |
| MRR | 0.068034 | **0.556740** |
| MTTC (lower is better) | 9.81 | **3.21** |
| TechnicalScore | 0.106710 | **0.815322** |

See [the technical report](docs/technical_report.md) for the locked split,
scenario metrics, ablations, latency, memory, model-cost disclosure, and
limitations.

## Requirements

- Python 3.10 or newer (verified with Python 3.14.7)
- SQLite compiled with FTS5 (present in standard macOS/Homebrew Python builds)
- About 1 GB free RAM; measured peak was 733 MB
- No third-party Python packages

`requirements.lock` intentionally contains no packages.

## Get and verify the official catalog

The catalog is an organizer artifact and is intentionally ignored by Git.

```bash
mkdir -p data/releases
gh release download participant-kit \
  --repo TechJam2026/techjam-conversational-search \
  --pattern catalog.jsonl.gz --pattern SHA256SUMS \
  --dir data/releases
```

Verify the catalog archive digest is:

```text
07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8  catalog.jsonl.gz
```

Then decompress it:

```bash
gzip -dc data/releases/catalog.jsonl.gz > data/catalog.jsonl
test "$(wc -l < data/catalog.jsonl | tr -d ' ')" = 50000
```

## Run

The official harness adapter is `starter/agent.py`; the submission entrypoint is
also exported from top-level `agent.py`.

```bash
python3 -m evaluator.local_evaluator
```

Run contract/failure-path tests:

```bash
python3 -m unittest -v
```

Run the locked tuning, holdout, or all-public measurement harness:

```bash
python3 -m evaluation.run_public_eval --split tuning
python3 -m evaluation.run_public_eval --split holdout
python3 -m evaluation.run_public_eval --split all
```

The holdout command is for reproduction after configuration is frozen, not for
iterative tuning. Generated `results*.json` and `evaluation/results/` are ignored.

## Architecture

The agent builds three local retrieval structures at startup:

- normalized product records and reliable facet maps;
- field-weighted in-memory SQLite FTS5;
- a catalog-derived 256-dimensional signed feature-hash index.

Per-session typed state tracks diagnostic route probabilities, hard/soft
evidence, decay, no-preference tombstones, intent generation, profile priors,
and rejected recommendations. Evidence activates retrieval routes, which are
fused with fixed weighted reciprocal-rank fusion,
then confidence-aware filters and a top-100 reranker apply exact phrases,
coverage, title relevance, and a small quality prior. Broad queries receive a
diverse shortlist and a composite clarification. Later questions use candidate
entropy, turn ten never asks, and missed recommendations rotate out. An override
revokes prior non-category evidence and clears old exclusions.

The rendered architecture source is [docs/architecture.mmd](docs/architecture.mmd).

## Optional OpenAI enhancement

The frozen competition configuration keeps network enhancement **off by
default** because no credentialed holdout experiment was run. The implementation
is available for an explicitly opted-in experiment only:

```bash
export OPENAI_API_KEY='set-this-in-your-shell-only'
export SHOPPING_COPILOT_OPENAI=1
python3 -m evaluator.local_evaluator
```

Never commit the key. The path uses `gpt-5.6-luna`, Responses API Structured
Outputs, `reasoning.effort="none"`, `store=false`, at most two calls per session,
a 2.5-second timeout, no retry, and a circuit breaker. It sees distilled state
and at most 30 catalog-valid candidates. Every update/order is validated; any
missing key, opt-out, timeout, malformed response, or network failure immediately
retains the deterministic offline result.

## Demonstrations and submission

```bash
python3 -m demos.run_demos
```

This prints four deterministic Buying, Browsing, Override, and Boundary traces.
See [demo traces](docs/demo_traces.md) and the
[recording/Devpost runbook](docs/recording_devpost_runbook.md). Paste-ready
[Devpost copy](docs/devpost_submission.md) and a timed
[demo script](docs/demo_script.md) are also included.

Publication remains an account-holder workflow; this repository contains no
automatic push, video-upload, or Devpost-submission behavior.

To reproduce the optional narrated demo video on macOS, install FFmpeg with
H.264/AAC support and run `python3 scripts/build_demo_video.py`. The builder also
uses the built-in `say` command and Swift/AppKit to synthesize narration and
render slides; these media-tool requirements do not apply to the submitted
agent or evaluator. Generated media stays under ignored `output/`.

## Provenance

This work is based on the official participant kit at upstream commit
`34078351e1c3615e5505a2e829600b56a542e462`. See
[UPSTREAM.md](UPSTREAM.md). The catalog, secrets, caches, and generated results
are not committed.
