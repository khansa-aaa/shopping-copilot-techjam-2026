# Three-minute demo script

Use `python3 -m demos.run_demos` for the live terminal section. Hide shell history,
environment variables, notifications, private tabs, and account information.

## 0:00–0:20 — Problem

“Shopping Copilot solves conversational product search when intent is incomplete
or changes mid-session. The goal is to identify the exact catalog product as
early and as highly ranked as possible across ten turns.”

## 0:20–0:45 — Architecture

“At startup, the agent builds three offline indexes over 50,000 products:
weighted full-text search, structured facets, and a catalog-derived dense
feature-hash index. Their rankings are fused, confidence-filtered, and reranked
locally.”

## 0:45–1:20 — Browsing trace

“Here the customer begins broadly with basketball products. The agent returns a
diverse shortlist and asks one composite clarification. After the customer
reveals polyester constraints, accumulated evidence places the verified target
at rank one.”

## 1:20–1:55 — Override trace

“This session starts with an older style preference. When the customer explicitly
changes direction, the agent advances its intent generation, revokes prior
non-category evidence, clears old exclusions, and ranks the new target first.”

## 1:55–2:20 — Boundary and safety

“For ‘no preference’ answers, tombstones prevent repeated questions. Candidate
rotation avoids showing the same failed shortlist, while deterministic validation
guarantees unique catalog-valid recommendations and no question on turn ten.”

## 2:20–2:45 — Results

“On the unmodified 200-session public evaluator, TechnicalScore improved from
0.106710 to 0.815322, with 0.985 HitRate, 0.556740 MRR, and 3.21 mean turns to
conversion. Median response latency was 20.7 milliseconds.”

## 2:45–3:00 — Practicality and close

“The frozen configuration is fully offline, used zero model tokens, and cost zero
dollars. Its main tradeoff is 733 megabytes of peak RAM. Shopping Copilot shows
that disciplined state, retrieval, and clarification can outperform a
model-dependent design.”
