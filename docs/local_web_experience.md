# Local web experience

This is the human-facing layer around the same Shopping Copilot Agent used by
the competition harness. It is complete enough to demonstrate a realistic
shopping journey locally, but it is not a hosted store, a live Amazon client, or
a checkout surface.

## Start it

From the repository root:

```bash
scripts/setup_local_web.sh
scripts/run_local_web.sh
```

Then open <http://127.0.0.1:8000>. Keep the terminal running. The startup screen
automatically polls the local health endpoint while the 50,000-product index is
built. This normally takes about 17 seconds on the measured Mac.

`setup_local_web.sh` performs bounded, reproducible preparation:

1. verifies Python 3.10+ and Node.js 20.19+, 22.13+, or 24+;
2. verifies the official catalog's checksum and 50,000-row count, or verifies
   and unpacks the official archive if it is present;
3. creates `.venv-demo` and installs the hash-locked FastAPI dependencies;
4. runs `npm ci` from the checked-in frontend lock; and
5. type-checks and builds the React app through its build command.

`run_local_web.sh` runs setup automatically when those artifacts are missing or
when dependency locks, the catalog, frontend source, configuration, or
`demo/web/public` assets are newer than the successful setup/build marker. It
then verifies both the exact official catalog checksum and 50,000-row count on
every launch before starting one Uvicorn worker on loopback port 8000. It does
not open a public port or create a cloud resource.

## A representative journey

1. Choose a starter card or type a natural request, such as “I need a
   lightweight travel backpack under $70.”
2. Read the Copilot's response and inspect the ranked shortlist.
3. Use the suggested replies or add another must-have in your own words.
4. Save interesting products, select two or three for comparison, and open a
   card for snapshot attributes and match reasons.
5. Select **Different options** to exercise unseen-candidate rotation.
6. Select **Change direction** and describe the new need to exercise stale-slot
   revocation and a new intent generation.
7. Open **How it decided** to see the current hard constraints, softer
   preferences, skipped attributes, diagnostic route probabilities, retrieval
   routes, response time, and optional-model status.
8. Export the transcript as Markdown or JSON if useful. Exports contain the
   displayed conversation and response data, so review them before sharing.

The conversation ends at turn ten, matching the competition contract. Restart
creates a clean server-side Agent session. Saved products persist only in that
browser's `localStorage`; they are not uploaded or placed into a cart.

## Modes

### Offline benchmark

This mode uses the frozen deterministic retrieval configuration that produced
the reported public-evaluator metrics. It makes no OpenAI call and remains the
authoritative reliability path. It is the initial web mode: shopping messages,
distilled preferences/state, and catalog retrieval remain within the browser and
loopback service on this Mac. An Amazon verification link leaves the local app
only when the user deliberately opens it.

### Hybrid

Hybrid is an optional, per-session shopper-facing mode. With no
`OPENAI_API_KEY`, the complete experience remains offline. When a key is
available, selecting Hybrid starts a fresh Hybrid-capable local session and
presents a disclosure with an explicit consent checkbox. All message actions are
blocked until that checkbox is selected, so no shopping context is sent merely
by changing the mode. Consent is reset whenever a new session is created.

After consent, the local service may ask `gpt-5.6-terra` to reorder only an
already-valid top-30 candidate set and suggest validated soft updates. The
browser never receives the key. The web profile uses low reasoning,
`store=false`, a six-second timeout, no retry, a maximum of ten calls per
session, and a 65% model/order blend. Hard filters, catalog membership, output
schema, and final validation stay deterministic.

For a credentialed run:

```bash
export OPENAI_API_KEY='set-this-in-your-shell-only'
scripts/run_local_web.sh
```

For each consented Hybrid turn, OpenAI receives the current shopping message,
distilled preferences/session state, and at most 30 catalog-valid candidate
summaries. Do not expose the key in shell history, screenshots, exports, logs,
`.env`, or Git. Current account access and pricing remain the account holder's
responsibility. Returning to Offline starts a new local-only Agent session.

## Snapshot and commerce disclosure

Every result is backed by the challenge's fixed 50,000-item text and metadata
snapshot derived from Amazon Reviews 2023, category
`Clothing_Shoes_and_Jewelry`. The supplied competition data contains no product
images or live commerce feed. The interface therefore uses neutral category
art, not fabricated product photography.

Displayed price, store, rating, review count, features, and details are snapshot
fields. They may be incomplete or stale. Marketplace selection changes only the
Amazon domain used by **Check on Amazon**. That link opens a search for the
catalog `parent_asin` so the user can independently verify the current listing.
Shopping Copilot does not claim availability, perform checkout, add to cart, or
receive an affiliate commission in this local build.

An environment-gated Amazon Creators API seam exists, but it deliberately
returns no enrichment until accepted credentials and a credentialed contract
test are available. Snapshot data is never relabeled as live data.

## What the API guarantees

The browser calls only same-origin local endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Read indexing status, catalog count, modes, and marketplaces |
| `POST /api/sessions` | Create a server-owned ten-turn Agent session |
| `POST /api/sessions/{id}/messages` | Advance exactly one expected turn |
| `DELETE /api/sessions/{id}` | Remove the local session |

Create and message requests carry UUID idempotency keys. Repeating the same
request safely replays the first result; reusing its ID with different content
is rejected. The server owns `turn` and `top_k`, serializes Agent access around
the shared SQLite connection, and rolls back state if the Agent itself fails. If
presentation assembly fails after a valid Agent result, that result is preserved:
the browser must retry the same request ID, and the server resumes assembly
without rerunning retrieval or a potentially billable model call. New turns stay
blocked until that preserved result completes. The service also limits bodies to
16 KB, expires sessions after two hours, caps the local session pool, permits
only loopback hostnames, and emits restrictive browser headers.

The response keeps the exact official Agent payload nested under
`agent_response`. Product display metadata, quick replies, snapshot disclosure,
diagnostics, and latency/cost metadata remain outside that scored contract.

Hybrid consent is a local-UI interaction gate, not a server-side consent ledger:
the Send and starter controls remain blocked until the per-session checkbox is
selected. A direct API client can still request `mode="hybrid"` and is
responsible for obtaining its own consent before sending a message. A public
service would need durable, auditable server-side consent policy.

## Verification

Run the local stack's automated checks after setup:

```bash
.venv-demo/bin/python -m unittest discover -s demo/api/tests -v
npm --prefix demo/web run typecheck
npm --prefix demo/web run test:run
npm --prefix demo/web run build
```

Then run the server and manually verify at desktop and narrow widths:

- startup progresses automatically to a fresh session;
- the initial session is Offline and displays the local-only privacy disclosure;
- a starter and a typed query both return ten or fewer products;
- suggested replies advance exactly one turn;
- retry does not duplicate evidence;
- save, details, compare, export, marketplace, offline mode, and restart work;
- **Change direction** replaces stale preferences;
- expert diagnostics truthfully show offline, fallback, or applied hybrid mode;
- when a key is available, Hybrid message actions remain blocked until the
  consent checkbox is selected, and another restart clears that consent;
- `Escape` closes dialogs, focusable controls have labels, and keyboard submit
  works; and
- the snapshot and no-purchase disclosures stay visible.

Automated Agent scoring remains separate:

```bash
python3 -m unittest -v
python3 -m evaluator.local_evaluator
```

## Judge path versus public-product path

Automated judges need only the ignored official catalog plus Python: they import
`starter.agent.Agent` and invoke the organizer's `reset` / `respond` protocol.
The web dependencies and server are not in that critical path. Human reviewers
can run the commands above to assess the complete experience.

A real public product would require work outside this submission's authorized
scope: a licensed current catalog and availability feed, production database and
cache, authentication and tenant isolation, encrypted persistence, privacy and
deletion controls, rate limits and abuse defenses, secrets management,
monitoring/alerts, backup and recovery, regional tax/affiliate/marketplace legal
review, accessibility and security audits, capacity/load testing, and a
maintained deployment. Until those gates are met, this is a production-shaped
local product experience, not a production release.
