# Three-minute demo script

This is the live-recording fallback outline. The preferred evidence-checked cut
uses the self-contained narration in `scripts/build_final_demo_video.py` and is
written to `output/demo/shopping-copilot-techjam-final.mp4`.

Run `scripts/run_local_web.sh` before recording and keep
`python3 -m demos.run_demos` available as deterministic terminal evidence. Hide
shell history, environment variables, notifications, private tabs, and account
information. The outline remains under Devpost's three-minute limit.

## 0:00–0:19 — Problem

“Shoppers rarely begin with a perfect query. They add constraints, reject
options, and sometimes change direction. Ordinary keyword search loses that
conversation. Shopping Copilot reduces repeated searching and scrolling by
finding the exact catalog product as early and as highly ranked as possible.”

## 0:19–0:37 — Product and architecture

“At startup, the agent builds three offline indexes over 50,000 products:
weighted full-text search, structured facets, and a catalog-derived dense
feature-hash index. The same engine powers the official judge adapter and this
local conversational product. Their rankings are fused, confidence-filtered,
and reranked locally.”

## 0:37–0:58 — Browsing trace

“I begin broadly with basketball products. Shopping Copilot returns a diverse,
explainable shortlist and asks one useful clarification. After I reveal a
polyester constraint, accumulated evidence retrieves the matching mesh
basketball shorts at rank one. I can save it, compare alternatives, or inspect
exactly which signals were remembered.”

## 0:58–1:13 — Override trace

“Now I use Change direction instead of restarting. The agent advances its intent
generation, revokes prior non-category evidence, clears old exclusions, and
ranks the new target first. The expert view makes that state transition visible.”

## 1:13–1:27 — Boundary and safety

“For ‘no preference’ answers, tombstones prevent repeated questions. Different
options rotates the failed shortlist, while deterministic validation guarantees
unique catalog-valid recommendations and no question on turn ten. A missing
model key or network failure safely retains the complete offline ranking.”

## 1:27–1:51 — Results

“On the unmodified 200-session public evaluator, TechnicalScore improved from
0.106710 to 0.815322, with 0.985 HitRate, 0.556740 MRR, and 3.21 mean turns to
conversion. Median response latency was 20.7 milliseconds.”

## 1:51–2:19 — Practicality and close

“The frozen configuration is fully offline, used zero model tokens, and cost zero
dollars, so it remains reliable without network access. The interface also
labels its fixed snapshot honestly and sends shoppers to Amazon only to verify a
current listing—no checkout occurs here. The main tradeoff is 733 megabytes of
peak RAM. This is a production-shaped local experience around a rigorously scored
retrieval core, not a claim of public deployment.”
