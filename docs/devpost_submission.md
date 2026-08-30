# Devpost submission copy

This document is paste-ready working copy. Before submitting, replace the
bracketed account-holder fields, verify every public link while signed out, and
match any authenticated form-specific character limits.

## Project name

Shopping Copilot

## One-line pitch

Offline-first conversational search that finds the right catalog product even
when shopping intent is vague, evolving, or replaced.

## Project description

Shopping rarely begins with a perfect query. Customers start broadly, reveal
constraints gradually, reject recommendations, or change direction completely.
Shopping Copilot is a headless conversational retrieval agent built to handle
that uncertainty across the official 50,000-product catalog.

On every turn, it returns a natural-language response, a structured clarification
attribute, and up to ten unique catalog-valid product IDs. It handles Buying,
Browsing, Focused, and Intent Override behavior; accumulates compatible evidence;
respects explicit “no preference” answers; rotates previously rejected
recommendations; and revokes stale constraints after an override.

At startup, Shopping Copilot normalizes nested and malformed catalog fields and
builds three local retrieval structures: field-weighted SQLite FTS5, reliable
structured facet maps, and a 256-dimensional catalog-derived signed feature-hash
index. Evidence activates multiple retrieval routes, which are combined using
fixed weighted reciprocal-rank fusion and followed by confidence-aware filtering
and top-100 reranking. Broad queries receive diverse candidates and a
high-information clarification; turn ten never asks another question.

The frozen competition configuration runs entirely offline with Python’s
standard library. An optional GPT-5.6 Luna enhancement is implemented behind
explicit environment opt-in, strict validation, a two-call limit, timeout, and
circuit breaker, but it was disabled for every reported evaluation because no
credentialed holdout experiment justified enabling it.

Using the unmodified 200-session public evaluator, the frozen agent achieved:

- HitRate@10: **0.985**
- MRR: **0.556740**
- MTTC: **3.21**
- TechnicalScore: **0.815322**, up from the official weak baseline of **0.106710**
- Response latency: **20.7 ms p50 / 55.5 ms p95**
- Actual model usage and API cost: **0 tokens / $0.00**

The strongest engineering lesson was that conversational state and clarification
policy mattered more than adding model complexity. Ablations showed major losses
when state accumulation, clarification, or recommendation rotation was removed.

Current limitations include approximately 733 MB peak RAM, only ten public
Boundary examples, a feature-hash dense index rather than pretrained embeddings,
and no claim of performance on the organizer’s private judging set. Future work
would add a disk-backed index and run controlled trials of profile ranking and
optional model reranking.

## Technologies

Python 3.10+, SQLite FTS5, structured facet retrieval, signed feature hashing,
weighted reciprocal-rank fusion, deterministic session-state management, and an
optional OpenAI Responses API / GPT-5.6 Luna enhancement.

## Links and account-holder fields

- Public repository: `[PUBLIC_GITHUB_URL]`
- Three-minute YouTube demo: `[PUBLIC_YOUTUBE_URL]`
- Team roster and contributions: Khansa and Naaman jointly contributed across
  problem framing, system architecture, implementation, evaluation,
  documentation, and demo preparation.
- Track/category: the account holder selects the official conversational-search
  and e-commerce track shown in the authenticated Devpost form.
- Eligibility and legal attestations: the account holder reviews and accepts
  these personally in Devpost.

## Final evidence statement

The reported result is from the frozen offline configuration. Local tests and
evaluation prove only the supplied local bundle; public-link accessibility and
successful Devpost submission must be confirmed separately by the account holder.
