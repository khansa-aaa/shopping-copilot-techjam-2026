# Shopping Copilot technical report

## Executive result

Shopping Copilot is an offline-first multi-turn retrieval agent with both the
official headless contract and a local end-to-end web experience. It preserves
the organizer's frozen 50,000-product catalog, exact-ASIN scoring, ten-turn
protocol, and `Agent.reset` / `Agent.respond` contract. The React/FastAPI layer
does not alter the scored response schema or the frozen evaluation path.

On the unmodified 200-session public evaluator, the frozen offline configuration
improves TechnicalScore from `0.106710` to `0.815322`.

## Architecture

```mermaid
flowchart TB
  E[Official evaluator] --> A[Strict Agent contract]
  U[Local shopper] --> UI[React experience]
  UI --> API[Loopback FastAPI adapter]
  API --> A
  A --> S[Typed session state]
  S --> R{Soft route probabilities}
  R --> F[Weighted FTS5]
  R --> X[Structured facets]
  R --> D[256D dense hash index]
  R --> P[Optional profile prior]
  F --> WRF[Weighted reciprocal-rank fusion]
  X --> WRF
  D --> WRF
  P --> WRF
  WRF --> H[Filter relaxation and top-100 rerank]
  H --> C[Clarify, diversify, rotate unseen]
  C --> V[Deterministic output validator]
  UI -. explicit per-session consent .-> O[Bounded OpenAI enhancement]
  S -. consented distilled state .-> O
  H -. at most 30 valid candidates .-> O
  O -. validated order or offline fallback .-> H
  V --> API
```

The adapter owns session identifiers, expected turns, ten-turn enforcement,
idempotent create/message requests, and display enrichment. It serializes access
to the shared in-memory Agent/SQLite structures and preserves the previous Agent
state if a turn raises. The official Agent response is returned unchanged under
`agent_response`; product display fields, quick replies, snapshot disclosures,
latency/cost data, and expert diagnostics remain outside the scoring contract.

The React client adds a conversational workspace, suggested replies, explicit
intent override, unseen-option rotation, local shortlist, two-to-three-product
comparison, details, Markdown/JSON export, marketplace verification links, and
transparent expert diagnostics. It defaults to the local-only Offline mode and
requires explicit, per-session UI consent before Hybrid data transmission. It is
served by the same loopback process after a static production build.

### Catalog preparation

Every catalog field is normalized, including nested `details`, scalar/list text
variants, nulls, and malformed string prices. Startup constructs:

1. reliable material/color/brand/category facet maps;
2. field-weighted SQLite FTS5, emphasizing title then category/features/details;
3. 256-dimensional signed feature-hash vectors using catalog document frequency,
   capped term frequency, normalization, and a small fixed synonym map.

All structures are local and in memory. The catalog itself remains an ignored
organizer artifact.

### Conversation state and routing

`SessionState` stores route probabilities, typed evidence with confidence and
hardness, turn, intent generation, no-preference tombstones, profile priors,
token usage, and prior rejected recommendations. Hard evidence persists; soft
evidence decays by `0.84` per later turn.

State records diagnostic likelihoods for Buying, Browsing, Focused, and Override
instead of persisting a single brittle classification. The frozen scorer does
not treat those likelihoods as learned weights: evidence activates the relevant
routes, which use fixed, reproducible fusion weights. Compatible constraints
accumulate. An explicit override increments the intent generation, retains
category context, revokes older non-category evidence, clears tombstones, and
clears exclusions.

### Retrieval and clarification

Conjunctive/exact, structured, BM25, dense, category, and optional profile routes
produce catalog-valid candidates. Weighted reciprocal-rank fusion combines them.
Only reliable material/color/brand and parsed budget evidence can hard-filter.
Filters are applied strongest-first, and any filter that would empty the set is
relaxed immediately.

The top 100 are reranked with fused score, query coverage, title overlap, exact
evidence phrases, route agreement, and a small rating/popularity prior. After an
implicit rejection, already-seen top-10 products rotate behind unseen products;
overrides clear that exclusion set.

With no non-category hard constraint and more than 500 candidates or weak score
separation, the agent returns ten category/brand-diverse candidates and one
composite `ask_attribute="other"` question. Later questions maximize entropy over
available candidate facets, with practical fallbacks. Tombstoned attributes are
not repeated, and turn ten always returns `ask_attribute=null`.

### Optional OpenAI paths

The optional implementation follows the OpenAI Responses API and GPT-5.6 Luna
model documentation:

- model `gpt-5.6-luna`;
- Structured Outputs with a strict JSON Schema;
- `reasoning.effort="none"`, `store=false`;
- distilled state plus at most 30 already-valid candidates;
- at most two calls per session, 2.5-second timeout, no retry;
- instance-wide 60-second circuit breaker after failure;
- deterministic validation of slot updates, query rewrite, candidate subset, and
  next attribute.

References:
[Responses API create](https://developers.openai.com/api/reference/cli/resources/responses/methods/create),
[GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna),
[GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra).

This conservative path is disabled in the frozen scored configuration because no
credentialed holdout experiment was available. `OPENAI_API_KEY` was absent
during all reported runs. Explicit evaluator use additionally requires
`SHOPPING_COPILOT_OPENAI=1`; otherwise the network path is unreachable.

The local web experience has a separate product-exploration profile: model
`gpt-5.6-terra`, low reasoning, `store=false`, six-second timeout, no retry, up
to ten calls in a ten-turn session, and a 65% blend between deterministic and
validated model ordering. Offline is the initial mode and keeps shopping
messages, distilled preferences/state, and retrieval on the local Mac. With
`OPENAI_API_KEY` present, a user may explicitly consent for one Hybrid session;
only then does each Hybrid turn send the current message, distilled
preferences/session state, and at most 30 already-valid candidate summaries to
OpenAI. Missing credentials or any model failure leaves the complete offline
ranking in place and surfaces the fallback status to the user.

The web profile is an unscored experience enhancement. It does not replace the
frozen offline result or constitute holdout evidence.

The bounded credentialed helper in `evaluation/run_hybrid_eval.py` separates a
32-session tuning-only calibration from a 32-session post-freeze exploratory
audit. The latter is drawn from the 40 public sessions already inspected for the
offline freeze. It is therefore neither untouched nor a second locked
validation set, and its outcome must never enable, disable, or change the
configuration. The legacy phase value `validation` is retained only for CLI
compatibility. A dry run emits selection/configuration hashes and a budget plan;
it performs no scoring run or model call and is not performance, token, cost, or
network evidence.

## Evaluation discipline

The split implementation is in `evaluation/run_public_eval.py`. It stratifies by
the released `(scenario_type, difficulty_bucket)` fields. Within each stratum,
SHA-256 order with seed `techjam-shopping-copilot-v1` assigns the first 20% to a
locked holdout: 16 Buying/easy, 16 Browsing/medium, 6 Override/hard, and 2
Boundary/medium sessions. The remaining 160 are the tuning set.

- Tuning IDs SHA-256: `2787f371644c4aec0069a494edd3f180771c5dbe87e28297ddb505dd335a9ce4`
- Holdout IDs SHA-256: `a98c19beed4fb935882f7d209def1548764cb0dafaf1772849291f886d5dc8fc`
- All-public IDs SHA-256: `653fa55317a4b659738e3a3e260f8af1a600071d1c668b3fcfedb727063a958b`

A pre-split architecture smoke run occurred before split locking and is excluded
from selection evidence. Component decisions then used only the 160-session
tuning set. The 40-session holdout was inspected once after freezing dense on,
profile ranking off, and network enhancement off. No configuration changed after
that holdout.

## Results

### Baseline to final, all 200 public sessions

| Metric | Weak baseline | Frozen offline agent | Change |
|---|---:|---:|---:|
| HitRate@10 | 0.125000 | 0.985000 | +0.860000 |
| MRR | 0.068034 | 0.556740 | +0.488706 |
| MTTC | 9.810000 | 3.210000 | -6.600000 |
| Efficiency | 0.119000 | 0.779000 | +0.660000 |
| TechnicalScore | 0.106710 | 0.815322 | +0.708612 |

### Final per-scenario metrics

| Scenario | N | HitRate@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Buying | 80 | 1.000000 | 0.522302 | 2.975000 |
| Browsing | 80 | 1.000000 | 0.601518 | 2.187500 |
| Intent Override | 30 | 0.933333 | 0.488558 | 5.800000 |
| Boundary | 10 | 0.900000 | 0.678571 | 5.500000 |

### Locked holdout (one inspection)

| Metric | Value |
|---|---:|
| HitRate@10 | 0.950000 |
| MRR | 0.513115 |
| MTTC | 3.425000 |
| TechnicalScore | 0.780434 |

### Tuning ablations

This ablation suite started from the all-local candidate with state, structured,
dense, clarification, rotation, and profile routes enabled. OpenAI was unavailable
and made no calls. Scores are TechnicalScore on only the locked 160.

| Configuration | TechnicalScore | Finding |
|---|---:|---|
| Candidate default | 0.818240 | Comparison reference |
| Without state accumulation | 0.597048 | Keep state |
| Without structured retrieval | 0.807480 | Keep structured retrieval |
| Without dense retrieval | 0.820432 | Interaction tested further |
| Without clarification | 0.457953 | Keep clarification |
| Without candidate rotation | 0.772857 | Keep rotation |
| Without profile use | **0.824044** | Disable profile ranking by default |
| Without OpenAI | 0.818240 | No credentialed evidence; disable by default |

The combined dense-off/profile-off check scored `0.820839`, so the frozen choice
is dense on/profile off (`0.824044` on tuning). The anonymized profile remains in
typed state and the route remains available for future evidence-backed trials.

## Runtime, token, cost, and offline disclosures

Measured on the local macOS runner with Python 3.14.7, 50,000 products, and all
200 public sessions:

| Measure | Result |
|---|---:|
| Startup/index time | 17.027 s |
| `respond` calls | 639 |
| Response latency p50 | 20.677 ms |
| Response latency p95 | 55.521 ms |
| Response latency max | 121.880 ms |
| Peak RAM | 732.828 MB |
| Prompt tokens | 0 |
| Completion tokens | 0 |
| Actual API cost | $0.00 |

The final result is network-independent by configuration: OpenAI is off, no
third-party package or service is used, and API-failure tests verify immediate
fallback with one attempted call and no retry. The host itself was not placed in
an OS-level network namespace, so this is offline-path evidence rather than a
claim about network-isolation infrastructure.

Official GPT-5.6 Luna prices observed during implementation were $0.20 per million
input tokens and $1.20 per million output tokens. A conservative optional-session
estimate of two calls totaling 8,000 input and 1,000 output tokens is about
`$0.0028`; 200 such sessions would be about `$0.56`. This is an estimate only,
not measured spend, and current pricing/account access must be rechecked before
opting in.

The local web adapter estimates GPT-5.6 Terra turns at the prices observed during
implementation: $2.00 per million input tokens and $12.00 per million output
tokens. This value is shown for transparency only; no credentialed Terra call or
spend is included in the reported benchmark. Current pricing must be rechecked
before a model-enabled demonstration.

## Verification and safety

The automated core suite covers both entrypoints, reset-before-respond, strict schema,
unique valid recommendations, turn ten, deterministic sessions, state/override,
Boundary tombstones, soft decay, malformed catalog fields/prices, API timeout/no
retry/circuit breaker, and static prohibition on `ground_truth` or `public_set`
references in the runtime Agent module. The original evaluator tests remain
unchanged and pass.

Separate API tests exercise health/startup behavior, session and message
validation, idempotent replay/conflict handling, server-owned turns, exact nested
Agent responses, and security headers. Frontend checks cover TypeScript, rendered
interaction states, and the production build. The local experience is also
reviewed manually at desktop and narrow widths; local HTTP success and rendered
browser behavior are treated as distinct gates.

The agent package never imports the public labels or evaluator. Evaluation and
demo helpers that verify target rank live in separate `evaluation/` and `demos/`
packages and are not imported by `agent.py`.

## Limitations

- Peak RAM is roughly 733 MB because FTS5, normalized text, facets, and dense
  vectors are all resident; a constrained judge may require a disk-backed index.
- Boundary has only ten public examples, so its estimate has high variance.
- Override cannot score before the official new intent, making its minimum MTTC
  inherently higher.
- The dense index is hash-based rather than a pretrained semantic embedding.
- Profile ranking and OpenAI enhancement are implemented but disabled because
  tuning/holdout evidence did not justify enabling them.
- All displayed product commerce fields are from a fixed Amazon Reviews 2023
  snapshot, not live inventory; Amazon links require user verification.
- The loopback web service is production-shaped but not a production deployment:
  it has no authentication, durable multi-user storage, live catalog contract,
  monitoring, rate-limit edge, or public hosting.

## Team contributions

Khansa and Naaman must jointly replace this handoff note with their actual,
specific contribution split before submission. No division of implementation,
evaluation, design, documentation, or demo work is inferred by this report.
They should review the final wording against commit history and working notes,
then use the reproducible checklist in `docs/team_handoff.md`.
