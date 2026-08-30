from __future__ import annotations

import argparse
import hashlib
import json
import resource
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from shopping_copilot.agent import Agent, AgentConfig


SPLIT_SEED = "techjam-shopping-copilot-v1"


def split_samples(samples: list[dict]) -> tuple[list[dict], list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for sample in samples:
        key = (str(sample["scenario_type"]), str(sample["difficulty_bucket"]))
        groups[key].append(sample)
    tuning: list[dict] = []
    holdout: list[dict] = []
    for key in sorted(groups):
        ranked = sorted(
            groups[key],
            key=lambda item: hashlib.sha256(
                f"{SPLIT_SEED}\0{item['sample_id']}".encode()
            ).hexdigest(),
        )
        holdout_count = round(len(ranked) * 0.20)
        holdout.extend(ranked[:holdout_count])
        tuning.extend(ranked[holdout_count:])
    return sorted(tuning, key=lambda item: item["sample_id"]), sorted(holdout, key=lambda item: item["sample_id"])


class TimedAgent:
    def __init__(self, inner: Agent) -> None:
        self.inner = inner
        self.latencies_ms: list[float] = []

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.inner.reset(session_id, user_profile)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        started = time.perf_counter()
        result = self.inner.respond(session_id, user_message, turn, top_k)
        self.latencies_ms.append((time.perf_counter() - started) * 1000)
        return result


def percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * probability))))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description="Locked-split TechJam evaluation with runtime metrics")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--split", choices=("tuning", "holdout", "all"), default="tuning")
    parser.add_argument("--ablate", action="append", default=[])
    parser.add_argument("--openai", action="store_true", help="Opt into the bounded API enhancement")
    parser.add_argument("--output")
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    tuning, holdout = split_samples(samples)
    selected = tuning if args.split == "tuning" else holdout if args.split == "holdout" else samples
    config = replace(AgentConfig(), openai_enhancement=args.openai)
    for ablation in args.ablate:
        config = config.with_ablation(ablation)

    startup_started = time.perf_counter()
    timed = TimedAgent(Agent(args.catalog, config=config))
    startup_seconds = time.perf_counter() - startup_started
    identifiers, categories, products = catalog_index(args.catalog)
    result = evaluate(timed, selected, identifiers, categories, products)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_ram_mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024
    result["evaluation_metadata"] = {
        "split": args.split,
        "split_seed": SPLIT_SEED,
        "sample_ids_sha256": hashlib.sha256(
            "\n".join(item["sample_id"] for item in selected).encode()
        ).hexdigest(),
        "ablations": args.ablate,
        "network_enhancement_requested": args.openai,
    }
    result["runtime"] = {
        "python": sys.version.split()[0],
        "startup_seconds": round(startup_seconds, 6),
        "respond_calls": len(timed.latencies_ms),
        "latency_ms_p50": round(statistics.median(timed.latencies_ms), 3),
        "latency_ms_p95": round(percentile(timed.latencies_ms, 0.95), 3),
        "latency_ms_max": round(max(timed.latencies_ms, default=0.0), 3),
        "peak_ram_mb": round(peak_ram_mb, 3),
    }
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "sessions"}, indent=2))


if __name__ == "__main__":
    main()
