# Khansa and Naaman handoff

Khansa and Naaman are submitting as a two-person team. This checklist supports
integration without presuming who did which work. Their actual contribution
split must be inserted and reviewed by both humans before submission.

## Actual contribution split — required before submission

- Khansa: `[INSERT SPECIFIC, EVIDENCE-BACKED CONTRIBUTIONS]`
- Naaman: `[INSERT SPECIFIC, EVIDENCE-BACKED CONTRIBUTIONS]`
- Reviewed by both teammates on: `[DATE / TIME]`

Use commit history and working notes as evidence. Remove these placeholders only
after both teammates agree the wording is accurate; do not substitute a blanket
claim that every task was joint.

## Source-of-truth rule

Choose one submission branch and one owner for each integration window. Before
moving code, both teammates record:

- repository URL, branch, and commit SHA;
- whether the working tree is clean;
- catalog provenance and row count;
- exact test/evaluator commands and results; and
- any uncommitted files that must remain local, especially credentials,
  catalogs, results, caches, video exports, and Devpost drafts.

Exchange reviewable commits or patches. Do not copy an entire repository over
the other checkout, merge generated results, or resolve conflicts by taking one
whole `agent.py` without reading the state/retrieval implications.

## Recommended lanes

Assign names together rather than inferring contribution ownership after the
fact:

| Lane | Deliverable | Integration gate |
|---|---|---|
| Retrieval and state | Agent, catalog normalization, ranking, overrides | Core tests plus locked evaluator metrics |
| Product experience | FastAPI adapter, React UX, accessibility, failure states | API/web tests plus rendered browser QA |
| Evidence and submission | Report, demo narrative, links, Devpost fields | Claims trace to reproducible local evidence |

One person may own more than one lane, but each final change has a named reviewer.
Record actual contributions truthfully in Devpost; do not use the generic lane
table as evidence that work happened.

## Integration order

1. Freeze a known-good offline Agent commit and rerun the all-public evaluator.
2. Review the other branch's changes by subsystem: state, retrieval, model path,
   API, UI, and docs.
3. Cherry-pick or manually integrate only changes with a clear hypothesis and
   test. Retune only on the locked 160-session tuning split.
4. The 40-session holdout has already had its one documented inspection. Do not
   reuse it as iterative feedback or describe it as untouched after new tuning;
   freeze any combined candidate on tuning, then report the all-200 public run
   transparently.
5. Rebuild the local web app against the final Agent and exercise Buying,
   Browsing, Override, and Boundary journeys.
6. Run the clean-room checklist below from the exact candidate commit.
7. Only then update reported numbers, record the demo, publish, and submit.

## Clean-room checklist for both teammates

```bash
git status --short
scripts/setup_local_web.sh
python3 -m unittest -v
python3 -m evaluator.local_evaluator
.venv-demo/bin/python -m unittest discover -s demo/api/tests -v
npm --prefix demo/web run typecheck
npm --prefix demo/web run test:run
npm --prefix demo/web run build
python3 -m demos.run_demos
```

Both teammates should compare the metrics with `docs/technical_report.md`, open
<http://127.0.0.1:8000>, and complete at least one override journey. One teammate
runs the commands; the other reviews the terminal output, web disclosures,
expert-mode status, and final diff.

## Submission-day ownership

- The signed-in Devpost account holder controls team invitations, eligibility
  attestations, track selection, and final submission.
- The GitHub repository owner confirms the final commit is public and readable
  while signed out.
- The video owner records/uploads the three-minute demonstration and confirms it
  is public and playable while signed out.
- Either teammate may prepare copy and evidence, but nobody shares API keys,
  passwords, MFA codes, payment details, or private identity documents.
- Save the submitted commit SHA, public repository URL, public video URL, and
  Devpost confirmation timestamp in a private team note.

If a late change is necessary, reopen the candidate, rerun the relevant full
gate, update every affected claim, and have the other teammate review it. A
working frozen submission is preferable to an unverified last-minute merge.
