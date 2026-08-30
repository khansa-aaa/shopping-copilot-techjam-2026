from __future__ import annotations

import json
from pathlib import Path

from evaluator.local_evaluator import (
    MAX_TURNS,
    TOP_K,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
    normalize_recommendations,
)
from starter.agent import Agent


DEMO_IDS = ("public_0149", "public_0006", "public_0072", "public_0131")


def run_trace(agent: Agent, sample: dict, catalog_ids: set[str], categories: dict, products: dict) -> dict:
    session_id = f"demo_{sample['sample_id']}"
    agent.reset(session_id, sample["user_profile"])
    target = str(sample["ground_truth"]["parent_asin"])
    card, behavior = materialize_hidden_fields(sample, products)
    effective = {**sample, "intent_card": card, "behavior": behavior}
    disclosed: set[str] = set()
    boundary_used = False
    override_applied = sample["scenario_type"] != "intent_override"
    user_message = initial_message(effective, coarse_category(categories[target]), disclosed)
    turns: list[dict] = []
    for turn in range(1, MAX_TURNS + 1):
        response = agent.respond(session_id, user_message, turn, TOP_K)
        ranked = normalize_recommendations(response["recommendations"], catalog_ids)
        hit_rank = ranked.index(target) + 1 if override_applied and target in ranked else None
        turns.append({
            "turn": turn,
            "customer": user_message,
            "agent_message": response["message"],
            "ask_attribute": response["ask_attribute"],
            "top_10": ranked,
            "verified_target_rank": hit_rank,
        })
        if hit_rank is not None or turn == MAX_TURNS:
            break
        override = effective.get("behavior", {}).get("override") or {}
        if not override_applied and turn + 1 == int(override.get("turn", 3)):
            override_applied = True
            value = str(override.get("new_value", ""))
            if value:
                disclosed.add(value)
            user_message = str(override.get("message"))
        else:
            user_message, boundary_used = customer_reply(
                effective, response["ask_attribute"], disclosed, boundary_used
            )
    return {
        "sample_id": sample["sample_id"],
        "scenario": sample["scenario_type"],
        "target": target,
        "turns": turns,
    }


def main() -> None:
    samples = {item["sample_id"]: item for item in load_jsonl("data/public_set.jsonl")}
    catalog_ids, categories, products = catalog_index("data/catalog.jsonl")
    agent = Agent("data/catalog.jsonl")
    traces = [run_trace(agent, samples[sample_id], catalog_ids, categories, products) for sample_id in DEMO_IDS]
    print(json.dumps(traces, indent=2))


if __name__ == "__main__":
    main()
