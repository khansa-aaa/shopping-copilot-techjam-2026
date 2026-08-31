# Three-minute demo script

Use `python3 -m demos.run_demos` for the live terminal section. Hide shell history,
environment variables, notifications, private tabs, and account information.
The reproducible narrated build is approximately 2:19; timings below match that
artifact and remain under Devpost's three-minute limit.

## 0:00–0:19 — Problem

“Shoppers rarely begin with a perfect query. They add constraints, reject
options, and sometimes change direction. Ordinary keyword search loses that
conversation. Shopping Copilot reduces repeated searching and scrolling by
finding the exact catalog product as early and as highly ranked as possible.”

## 0:19–0:37 — Architecture

“At startup, the agent builds three offline indexes over 50,000 products:
weighted full-text search, structured facets, and a catalog-derived dense
feature-hash index. Their rankings are fused, confidence-filtered, and reranked
locally.”

## 0:37–0:58 — Browsing trace

“This end-to-end trace is executed and checked during the video build. The
customer begins broadly with basketball products. The agent returns a diverse
shortlist and asks one composite clarification. After the customer reveals
polyester constraints, accumulated evidence retrieves the matching mesh
basketball shorts at rank one.”

## 0:58–1:13 — Override trace

“This session starts with an older style preference. When the customer explicitly
changes direction, the agent advances its intent generation, revokes prior
non-category evidence, clears old exclusions, and ranks the new target first.”

## 1:13–1:27 — Boundary and safety

“For ‘no preference’ answers, tombstones prevent repeated questions. Candidate
rotation avoids showing the same failed shortlist, while deterministic validation
guarantees unique catalog-valid recommendations and no question on turn ten.”

## 1:27–1:51 — Results

“On the unmodified 200-session public evaluator, TechnicalScore improved from
0.106710 to 0.815322, with 0.985 HitRate, 0.556740 MRR, and 3.21 mean turns to
conversion. Median response latency was 20.7 milliseconds.”

## 1:51–2:19 — Practicality and close

“The frozen configuration is fully offline, used zero model tokens, and cost zero
dollars, so it remains reliable without network access. Resolving vague or
changing intent in fewer turns can reduce repeated queries and catalog scrolling.
Its main tradeoff is 733 megabytes of peak RAM. On the public evaluator,
disciplined state, retrieval, and clarification dramatically outperformed the
official weak baseline.”
