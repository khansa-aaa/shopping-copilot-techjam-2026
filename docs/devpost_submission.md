# Devpost submission copy

This document is paste-ready working copy. Before submitting, replace the
bracketed account-holder fields, verify every public link while signed out, and
match any authenticated form-specific character limits.

## Project name

Shopping Copilot

## One-line pitch

Offline-first conversational shopping that turns vague, evolving intent into a
ranked, explainable shortlist.

## Project description

Shopping rarely begins with a perfect query. Customers start broadly, reveal
constraints gradually, reject recommendations, or change direction completely.
Shopping Copilot handles that uncertainty across the official 50,000-product
catalog through both the exact headless judging contract and a complete local
shopping experience.

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

The local React/FastAPI product makes that intelligence tangible. Shoppers can
begin with guided journeys or free text, answer contextual quick replies, ask
for different options, explicitly change direction, inspect why each result
matched, compare products side by side, save a browser-local shortlist, switch
marketplace verification links, export the session, and open an expert view of
intent signals, constraints, retrieval routes, latency, tokens, cost, and safe
fallback status. The API enforces server-owned turns and idempotent retries while
keeping the official Agent payload unchanged.

Every commerce field is labeled honestly: results are from the fixed TechJam
snapshot derived from Amazon Reviews 2023, not current Amazon inventory. The
dataset has no images, so the product uses neutral category art rather than
fabricated photography. Amazon links are user-initiated ASIN searches for current
verification; Shopping Copilot does not add to cart or purchase.

The frozen competition configuration runs entirely offline with Python’s
standard library. A conservative optional GPT-5.6 Luna enhancement is available
for scored experiments behind explicit opt-in. The web experience also supports
a bounded GPT-5.6 Terra reranker over at most 30 already-valid candidates, with
strict validation and visible fallback. The web app starts Offline and requires
explicit consent for each Hybrid session before sending the current shopping
message, distilled preferences/state, and candidate summaries to OpenAI. No
credentialed model result is included in the reported metrics because it was not
justified by holdout evidence.

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
snapshot rather than live commerce data, and no claim of performance on the
organizer’s private judging set. A public release would additionally require a
licensed live feed, authentication, durable storage, privacy/abuse controls,
observability, compliance review, load testing, and deployment ownership.

## Technologies

Python 3.10+, SQLite FTS5, structured facet retrieval, signed feature hashing,
weighted reciprocal-rank fusion, deterministic session-state management,
FastAPI, React, TypeScript, Vite, and optional OpenAI Responses API enhancements
with GPT-5.6 Luna/Terra profiles.

## Links and account-holder fields

- Public repository: `https://github.com/khansa-aaa/shopping-copilot-techjam-2026`
- Three-minute YouTube demo: `[PUBLIC_YOUTUBE_URL]`
- Team roster and contributions: Khansa led product direction and requirements,
  shaped the web experience, coordinated implementation and integration, and
  ran validation, evaluation, release review, and submission preparation.
  Naaman recorded the final voice-over, edited and exported the end-to-end demo,
  and reviewed the Browsing and Intent Override journeys shown in the recording.
  Both teammates must review this wording before the final rules attestation.
- Track/category: the account holder selects the official conversational-search
  and e-commerce track shown in the authenticated Devpost form.
- Eligibility and legal attestations: the account holder reviews and accepts
  these personally in Devpost.

## Final evidence statement

The reported result is from the frozen offline configuration. Local tests and
evaluation prove only the supplied local bundle; public-link accessibility and
successful Devpost submission must be confirmed separately by the account holder.
