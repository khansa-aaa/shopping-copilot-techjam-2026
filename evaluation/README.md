# Evaluation protocol

`run_public_eval.py` deterministically partitions the 200 public sessions by
`(scenario_type, difficulty_bucket)`. Within each stratum, sample IDs are
SHA-256 ranked with seed `techjam-shopping-copilot-v1`; the first 20% form the
locked 40-session holdout and the remaining 160 form the tuning set.

Tune only with:

```bash
python3 -m evaluation.run_public_eval --split tuning
```

After freezing configuration, inspect the holdout once and then report the
official all-public result. Generated result files belong in
`evaluation/results/` and are ignored by Git.
