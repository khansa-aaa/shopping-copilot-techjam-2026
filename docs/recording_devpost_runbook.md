# Recording and Devpost runbook

The official Devpost page lists the submission deadline as **1 September 2026,
12:00 pm SGT** and requires a written description, a public code repository, and
a public three-minute YouTube demo. Reconfirm the live Devpost fields and rules
before submission: <https://tiktoktechjam2026.devpost.com/>.

Reserve the final four hours (from 8:00 am SGT) for clean-room verification,
recording/upload recovery, public-link checks, and form review. These are
account-holder actions; no script in this repository publishes or submits.

Paste-ready form copy is in `docs/devpost_submission.md`; the timed narration is
in `docs/demo_script.md`.

## T-4 hours: freeze and verify locally

1. Stop feature changes. Record the final local commit hash if the account holder
   chooses to commit.
2. Confirm `git status --short` contains no catalog, result, cache, `.env`, or
   secret file.
3. Download and verify the official catalog as described in `README.md`.
4. Run `python3 -m unittest -v`.
5. Run `python3 -m evaluator.local_evaluator` and compare the four overall metrics
   with `docs/technical_report.md`.
6. Run `python3 -m demos.run_demos`; confirm the four scenarios complete and no
   credential/network prompt appears.
7. If an API key exists in the shell, leave `SHOPPING_COPILOT_OPENAI` unset for
   the frozen offline demo. Never show or print the key.

Local success proves only the local bundle, not GitHub visibility, YouTube
processing, Devpost acceptance, or judge-environment compatibility.

## T-3 hours: record the three-minute demo

Suggested timeline:

- 0:00–0:20 — problem and exact-ASIN/ten-turn objective;
- 0:20–0:45 — architecture diagram and offline fallback;
- 0:45–1:25 — Browsing trace: composite clarification to rank-1 result;
- 1:25–2:05 — Override trace: show evidence revocation and rank-1 result;
- 2:05–2:30 — Boundary handling and deterministic validation;
- 2:30–2:50 — baseline-to-final metrics and latency/cost disclosure;
- 2:50–3:00 — limitations and close.

Record only terminal commands/output and repository artifacts. Hide notifications,
shell history, environment variables, account emails, and private tabs. Do not
display `OPENAI_API_KEY` or payment/account dashboards.

## T-2 hours: user-controlled publication

1. Create or select the account holder's GitHub repository.
2. Review every tracked file with `git status` and `git ls-files`.
3. Confirm `data/catalog.jsonl`, `data/releases/`, generated results, `.env`, and
   caches are absent from tracked files.
4. Add the chosen GitHub remote and push only after this review.
5. Open the public repository in a signed-out/private browser and verify README,
   source, report, and setup steps are readable.
6. Upload the demo to the account holder's YouTube channel and wait for processing.
7. Verify the public video URL in a signed-out/private browser and check
   duration/audio/readability.

## T-1 hour: complete Devpost without submitting early by accident

Populate and review:

- project name and one-line pitch;
- problem, solution, and technical implementation;
- public GitHub URL;
- public three-minute YouTube URL;
- technologies: Python, SQLite FTS5, deterministic hybrid retrieval; disclose
  GPT-5.6 Luna as implemented but disabled in the frozen run;
- metrics, latency, RAM, token use, actual cost, and offline behavior;
- limitations and real team-member contributions;
- required track/category selections and eligibility confirmations.

Use only truthful evidence from the report. Do not describe local checks as a
successful upload, public visibility, or accepted submission.

## Final 30 minutes: account-holder submission

1. Reopen every link from the Devpost preview.
2. Confirm the selected track and team roster.
3. Confirm the repository and video are accessible without the owner's session.
4. Review legal/eligibility attestations personally.
5. The account holder clicks the final submit button.
6. Save the Devpost confirmation page/receipt and timestamp.

If GitHub, YouTube, or Devpost is unavailable near the deadline, prioritize a
minimal truthful submission with working public links. Do not fabricate proof or
claim that a pending upload is complete.
