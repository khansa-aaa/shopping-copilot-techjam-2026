# Evaluation protocol

`run_public_eval.py` deterministically partitions the 200 public sessions by
`(scenario_type, difficulty_bucket)`. Within each stratum, sample IDs are
SHA-256 ranked with seed `techjam-shopping-copilot-v1`; the first 20% form the
locked 40-session holdout and the remaining 160 form the tuning set.

Tune only with:

```bash
python3 -m evaluation.run_public_eval --split tuning
```

The offline configuration was frozen and the 40-session holdout was inspected
once, as recorded in `docs/technical_report.md`. It is therefore historical
holdout evidence, not an untouched set available for another tuning cycle.
Generated result files belong in `evaluation/results/` and are ignored by Git.

## Bounded hybrid evaluation

`run_hybrid_eval.py` adds a credentialed evaluation-only lane for the optional
GPT-5.6 Terra reranker. It deterministically selects a 32-session calibration
subset from the 160-session tuning split. Calibration is the only Hybrid phase
that may inform experimental parameters. The script also selects a disjoint
32-session **post-freeze exploratory audit** subset from the already-inspected
offline holdout. That second subset is not untouched, is not a locked validation
set, and has no authority to enable, disable, or change the configuration.
Selection uses only sample ID, scenario, and difficulty metadata; the runtime
Agent still receives only the official `reset` and `respond` contract.

Inspect the exact sample IDs, configuration hash, and budget plan without a
credential or network call:

```bash
python3 -m evaluation.run_hybrid_eval --dry-run
```

The dry run is a manifest only. It proves deterministic selection and records
dataset/configuration hashes and the proposed budget guard. It does **not** run
the evaluator, call OpenAI, measure tokens or spend, or provide model-quality
evidence. Its JSON explicitly reports `evaluation_executed=false` and
`network_usage_status=none_dry_run`.

Once `OPENAI_API_KEY` is present in the local environment, run calibration:

```bash
python3 -m evaluation.run_hybrid_eval --phase calibration
```

After freezing from tuning-only calibration, the optional exploratory audit can
be reported without changing the configuration. The phase spelling
`validation` remains only for CLI compatibility:

```bash
python3 -m evaluation.run_hybrid_eval \
  --phase validation \
  --acknowledge-post-freeze-audit
```

Running or reading that audit must never feed back into model choice, blend,
prompt, retrieval, thresholds, enablement, or any other configuration. Report it
as post-freeze exploratory evidence from a previously inspected public subset,
never as private-set performance, untouched holdout evidence, or selection
authority. The deprecated `--acknowledge-locked-validation` spelling is accepted
only as a hidden compatibility alias and should not appear in new evidence.

The lane uses `gpt-5.6-terra` with `reasoning.effort=low`, two calls at most per
session, and deterministic candidate/schema validation in the core Agent. It
estimates reported usage at $2 per million input tokens and $12 per million
output tokens. Further enhancement is disabled before the $10 hard cap whenever
the next request would consume a protected $1 operator reserve plus a $4.25
worst-case call allowance. Offline retrieval continues after any cutoff or API
failure. Calibration evidence defaults to
`evaluation/results/hybrid_calibration.json`; the exploratory phase defaults to
`evaluation/results/hybrid_post_freeze_audit.json`.
