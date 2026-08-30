from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from evaluation.run_public_eval import split_samples
from shopping_copilot.agent import Agent, AgentConfig


ABLATIONS = ("state", "structured", "dense", "clarification", "rotation", "profile", "openai")


def compact(result: dict) -> dict:
    return {
        key: result[key]
        for key in (
            "sample_count", "hit_rate_at_10", "mrr", "mttc", "efficiency",
            "recommended_technical_score", "scenario_metrics", "reported_token_usage",
        )
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run locked-tuning-set component ablations")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--output")
    args = parser.parse_args()
    tuning, _ = split_samples(load_jsonl(args.dataset))
    identifiers, categories, products = catalog_index(args.catalog)
    # Reconstruct the pre-freeze all-local candidate used by the documented
    # component study. The frozen Agent default intentionally has profile_use
    # disabled after this study showed a regression.
    baseline_config = AgentConfig(
        dense_retrieval=True,
        profile_use=True,
        openai_enhancement=False,
    )
    results = {
        "default_offline": compact(evaluate(
            Agent(args.catalog, baseline_config), tuning, identifiers, categories, products
        ))
    }
    for name in ABLATIONS:
        config = baseline_config.with_ablation(name)
        results[f"without_{name}"] = compact(evaluate(
            Agent(args.catalog, config), tuning, identifiers, categories, products
        ))
    if args.output:
        Path(args.output).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
