# Shopping Copilot — TechJam 2026

Shopping Copilot is an offline-first conversational product-retrieval system for
the TechJam Conversational E-Commerce Search Challenge. It now has two complete
ways to use the same engine:

- the official headless `Agent.reset` / `Agent.respond` contract used for
  exact-`parent_asin` judging; and
- a polished local web experience for shoppers, reviewers, and the demo.

The scored agent preserves the organizer's 50,000-item catalog and ten-turn
protocol. Its frozen default remains fully offline and uses only Python's
standard library.

| Metric | Official weak baseline | Shopping Copilot |
|---|---:|---:|
| HitRate@10 | 0.125 | **0.985** |
| MRR | 0.068034 | **0.556740** |
| MTTC (lower is better) | 9.81 | **3.21** |
| TechnicalScore | 0.106710 | **0.815322** |

See the [technical report](docs/technical_report.md) for the locked split,
scenario metrics, ablations, latency, memory, model-cost disclosure, and
limitations.

## Try the full local experience

### 1. Get the official catalog

The catalog is an organizer artifact and is intentionally ignored by Git.

```bash
mkdir -p data/releases
gh release download participant-kit \
  --repo TechJam2026/techjam-conversational-search \
  --pattern catalog.jsonl.gz --pattern SHA256SUMS \
  --dir data/releases
```

The expected archive digest is:

```text
07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8  catalog.jsonl.gz
```

The setup script verifies and unpacks that archive when `data/catalog.jsonl` is
not already present.

### 2. Set up once, then run

Requirements for the local web experience are Python 3.10+, Node.js 20.19+,
22.13+, or 24+, npm, SQLite FTS5, and about 1 GB of free RAM.

```bash
scripts/setup_local_web.sh
scripts/run_local_web.sh
```

Open <http://127.0.0.1:8000>. The first launch builds the local indexes and
usually takes about 17 seconds. Later launches reuse installed dependencies, but
rebuild the in-memory catalog index. Press `Ctrl-C` to stop the server.

On a fresh checkout, `scripts/run_local_web.sh` also runs setup automatically if
the locked dependencies or built interface are missing or stale. It includes
frontend source and public assets in the freshness check, and verifies the exact
official catalog checksum on every launch. The server binds only to `127.0.0.1`;
these commands do not deploy anything.

### 3. Shop conversationally

Start broad ("I need a travel backpack"), add must-haves ("leather and under
$50"), choose a suggested reply, request different options, or use **Change
direction** to replace an earlier preference. You can then:

- inspect match reasons and catalog attributes;
- compare up to three products;
- save a device-local shortlist;
- export the conversation as Markdown or JSON;
- switch Amazon marketplace links; and
- open **How it decided** to inspect intent signals, remembered constraints,
  retrieval routes, model status, tokens, latency, and estimated cost.

The interface is deliberately honest about its data. Results come from the fixed
50,000-item TechJam snapshot derived from Amazon Reviews 2023, not current Amazon
inventory. It contains no product images. Prices, sellers, ratings, availability,
and details may have changed. **Check on Amazon** opens an ASIN search for manual
verification; it never adds to cart or purchases.

The full interaction guide is in
[docs/local_web_experience.md](docs/local_web_experience.md).

## Offline and hybrid behavior

The web app starts in **Offline benchmark** mode. Shopping messages, remembered
preferences, and catalog retrieval stay on this Mac unless the user explicitly
enables Hybrid for the current session. No key or consent is needed to use the
complete interface. User-initiated Amazon verification links are a separate,
visible navigation out of the local app.

To try the optional web reranker, set the key only in the launching shell:

```bash
export OPENAI_API_KEY='set-this-in-your-shell-only'
scripts/run_local_web.sh
```

With a key available, selecting Hybrid presents a per-session disclosure. Only
after the user consents does that session send each current shopping message,
distilled preference/state data, and at most 30 already-valid catalog candidate
summaries to OpenAI. The profile uses `gpt-5.6-terra`, low reasoning, a
six-second timeout, up to ten calls in a ten-turn session, and a 65% model/order
blend. Deterministic validation remains authoritative; missing credentials or a
request failure immediately retains the offline ranking and shows **safe
fallback**. Never put a key in `.env`, frontend code, an export, a screenshot,
or Git.

The scored Agent has a separate conservative experiment profile:
`gpt-5.6-luna`, no reasoning, at most two calls, 2.5-second timeout, no retry,
and a circuit breaker. It is off by default and requires both environment values:

```bash
export OPENAI_API_KEY='set-this-in-your-shell-only'
export SHOPPING_COPILOT_OPENAI=1
python3 -m evaluator.local_evaluator
```

All published metrics above are from the frozen offline configuration: zero
model tokens and $0 actual API cost. That network-independent mode is also the
web app's initial state.

## How judges use it

Automated scoring does not depend on React, FastAPI, Node, or a browser. The
official evaluator imports `starter.agent.Agent`, calls `reset(session_id,
user_profile)`, then calls `respond(session_id, user_message, turn, top_k)` for
up to ten turns. The top-level `agent.py` exports the same contract.

```bash
python3 -m evaluator.local_evaluator
```

Human judges can additionally run the local web app to experience the same
state, retrieval, clarification, override, and recommendation logic end to end.
The web layer owns safe session IDs, turn ordering, idempotent retries, display
metadata, and local-only shortlist/export behavior; it does not change the
official response schema or scoring path.

## How this becomes a public product

The current build is intentionally local and competition-focused, but its
functionality models a real shopping workflow. A public release would keep the
conversation and retrieval core while replacing the local shell with a deployed,
multi-tenant service and licensed current-catalog integrations. It would also
need authentication, persistent encrypted storage, privacy/deletion controls,
rate limits, abuse prevention, observability, regional commerce/affiliate
compliance, live inventory and price verification, production accessibility and
security reviews, and deployment/runbook ownership. Those are explicit future
gates—not claims made by this repository.

## Architecture

The agent builds normalized catalog records and facet maps, field-weighted
SQLite FTS5, and a 256-dimensional catalog-derived signed feature-hash index.
Per-session typed state tracks route probabilities, hard and soft evidence,
decay, no-preference tombstones, intent generation, profile priors, and rejected
recommendations. Retrieval routes are fused with weighted reciprocal-rank
fusion, confidence-aware filters, and top-100 reranking. Broad requests receive
diverse candidates and an information-seeking clarification; stale evidence is
revoked after an override; turn ten never asks another question.

The local FastAPI adapter serializes access to the shared in-memory Agent,
enforces server-owned turns and ten-turn limits, and makes same-request retries
idempotent. The React client presents the conversation, results, shortlist,
comparison, export, and transparent expert diagnostics. See the rendered source
in [docs/architecture.mmd](docs/architecture.mmd).

## Verify

Core Agent contract and failure paths:

```bash
python3 -m unittest -v
python3 -m evaluator.local_evaluator
```

Local API and web experience after setup:

```bash
.venv-demo/bin/python -m unittest discover -s demo/api/tests -v
npm --prefix demo/web run typecheck
npm --prefix demo/web run test:run
npm --prefix demo/web run build
```

Locked tuning, holdout, or all-public measurement:

```bash
python3 -m evaluation.run_public_eval --split tuning
python3 -m evaluation.run_public_eval --split holdout
python3 -m evaluation.run_public_eval --split all
```

The holdout command is for reproduction after configuration is frozen, not for
iterative tuning. Generated results and caches are ignored.

## Demonstrations and team handoff

```bash
python3 -m demos.run_demos
```

This prints deterministic Buying, Browsing, Override, and Boundary traces. The
[demo traces](docs/demo_traces.md), [demo script](docs/demo_script.md),
[recording/Devpost runbook](docs/recording_devpost_runbook.md), and
[paste-ready Devpost copy](docs/devpost_submission.md) are included. The required
Khansa/Naaman contribution review and final handoff checklist are documented in
[docs/team_handoff.md](docs/team_handoff.md).

On macOS, the submission cut can also be rebuilt deterministically from the
captured local interface and repository evidence:

```bash
python3 scripts/build_final_demo_video.py --check-inputs
python3 scripts/build_final_demo_video.py
```

The builder rejects missing captures, changed evidence, incompatible media, and
videos at or above three minutes. It writes the ignored local artifacts to
`output/demo/shopping-copilot-techjam-final.{mp4,png,srt,json}`; the JSON manifest
records the input hashes, verified claims, duration, codecs, and output hash.

Publication remains an account-holder workflow. No script pushes a repository,
uploads a video, deploys a service, or submits Devpost.

## Provenance

The official `participant-kit` tag resolves to
`2a6cc8e776da66ce69b1cbd237838fbc43f32587`; this repository also incorporated
later official upstream clarifications through
`34078351e1c3615e5505a2e829600b56a542e462` before participant development.
See [UPSTREAM.md](UPSTREAM.md) for the exact upstream and user-owned remote
lineage, and [DATA_ATTRIBUTION.md](DATA_ATTRIBUTION.md) for dataset attribution.
The catalog, secrets, caches, generated web build, generated results, and local
virtual environment are not committed.
