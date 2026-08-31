from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import resource
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from evaluation.run_public_eval import SPLIT_SEED, split_samples
from shopping_copilot.agent import Agent, AgentConfig


MODEL = "gpt-5.6-terra"
REASONING_EFFORT = "low"
CALIBRATION_SEED = "techjam-shopping-copilot-hybrid-calibration-v1"
POST_FREEZE_AUDIT_SEED = "techjam-shopping-copilot-hybrid-post-freeze-audit-v1"
DEFAULT_CALIBRATION_SIZE = 32
DEFAULT_POST_FREEZE_AUDIT_SIZE = 32
HARD_BUDGET_CAP_USD = 10.0
OPERATOR_RESERVE_USD = 1.0
INPUT_USD_PER_MILLION = 2.0
OUTPUT_USD_PER_MILLION = 12.0

# Terra has a 1,050,000-token context window. Above 272K input tokens, the
# published rates are 2x input and 1.5x output. The enhancer caps output at 900
# tokens, so $4.25 is a rounded-up maximum modeled exposure for one request.
# This is deliberately much larger than the catalog reranker prompts in normal
# operation and protects the hard cap even when a response reports no usage.
WORST_CASE_CALL_RESERVE_USD = 4.25


Stratum = tuple[str, str]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sample_ids_sha256(samples: Sequence[dict]) -> str:
    return _sha256_text("\n".join(sorted(str(item["sample_id"]) for item in samples)))


def _stratum(sample: Mapping[str, object]) -> Stratum:
    return str(sample["scenario_type"]), str(sample["difficulty_bucket"])


def _allocate_strata(groups: Mapping[Stratum, Sequence[dict]], count: int) -> dict[Stratum, int]:
    total = sum(len(items) for items in groups.values())
    if isinstance(count, bool) or not isinstance(count, int) or not 0 < count <= total:
        raise ValueError(f"subset size must be an integer between 1 and {total}")

    quotas: dict[Stratum, int] = {}
    remainders: list[tuple[int, Stratum]] = []
    for key in sorted(groups):
        numerator = count * len(groups[key])
        quotas[key] = numerator // total
        remainders.append((numerator % total, key))

    remaining = count - sum(quotas.values())
    for _, key in sorted(remainders, key=lambda item: (-item[0], item[1])):
        if remaining == 0:
            break
        if quotas[key] < len(groups[key]):
            quotas[key] += 1
            remaining -= 1
    if remaining:
        raise ValueError("unable to allocate requested subset across strata")
    return quotas


def select_stratified(samples: Sequence[dict], count: int, seed: str) -> list[dict]:
    """Select by public metadata only; target labels never influence membership."""

    groups: dict[Stratum, list[dict]] = defaultdict(list)
    for sample in samples:
        groups[_stratum(sample)].append(sample)
    quotas = _allocate_strata(groups, count)
    selected: list[dict] = []
    for key in sorted(groups):
        ranked = sorted(
            groups[key],
            key=lambda item: (
                hashlib.sha256(f"{seed}\0{item['sample_id']}".encode("utf-8")).hexdigest(),
                str(item["sample_id"]),
            ),
        )
        selected.extend(ranked[: quotas[key]])
    return sorted(selected, key=lambda item: str(item["sample_id"]))


@dataclass(frozen=True, slots=True)
class HybridSelection:
    tuning: tuple[dict, ...]
    holdout: tuple[dict, ...]
    calibration: tuple[dict, ...]
    post_freeze_audit: tuple[dict, ...]


def build_selection(
    samples: Sequence[dict],
    *,
    calibration_size: int = DEFAULT_CALIBRATION_SIZE,
    post_freeze_audit_size: int = DEFAULT_POST_FREEZE_AUDIT_SIZE,
) -> HybridSelection:
    tuning, holdout = split_samples(list(samples))
    calibration = select_stratified(tuning, calibration_size, CALIBRATION_SEED)
    post_freeze_audit = select_stratified(
        holdout,
        post_freeze_audit_size,
        POST_FREEZE_AUDIT_SEED,
    )
    calibration_ids = {str(item["sample_id"]) for item in calibration}
    post_freeze_ids = {str(item["sample_id"]) for item in post_freeze_audit}
    if calibration_ids.intersection(post_freeze_ids):
        raise RuntimeError("calibration and post-freeze audit selections overlap")
    return HybridSelection(
        tuning=tuple(tuning),
        holdout=tuple(holdout),
        calibration=tuple(calibration),
        post_freeze_audit=tuple(post_freeze_audit),
    )


def _strata_counts(samples: Sequence[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        scenario, difficulty = _stratum(sample)
        counts[f"{scenario}/{difficulty}"] += 1
    return dict(sorted(counts.items()))


def selection_manifest(selection: HybridSelection) -> dict:
    def entry(samples: Sequence[dict], seed: str) -> dict:
        return {
            "count": len(samples),
            "seed": seed,
            "sample_ids_sha256": _sample_ids_sha256(samples),
            "strata": _strata_counts(samples),
            "sample_ids": sorted(str(item["sample_id"]) for item in samples),
        }

    return {
        "base_split": {
            "seed": SPLIT_SEED,
            "tuning_count": len(selection.tuning),
            "holdout_count": len(selection.holdout),
            "tuning_ids_sha256": _sample_ids_sha256(selection.tuning),
            "holdout_ids_sha256": _sample_ids_sha256(selection.holdout),
        },
        "calibration": entry(selection.calibration, CALIBRATION_SEED),
        "post_freeze_exploratory_audit": {
            **entry(selection.post_freeze_audit, POST_FREEZE_AUDIT_SEED),
            "source": "previously_inspected_offline_holdout",
            "tuning_authority": False,
            "untouched_holdout_claim": False,
        },
    }


def estimated_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    values = (prompt_tokens, completion_tokens)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise ValueError("token counts must be non-negative integers")
    return (
        prompt_tokens * INPUT_USD_PER_MILLION
        + completion_tokens * OUTPUT_USD_PER_MILLION
    ) / 1_000_000


@dataclass(slots=True)
class BudgetGuard:
    hard_cap_usd: float = HARD_BUDGET_CAP_USD
    operator_reserve_usd: float = OPERATOR_RESERVE_USD
    call_reserve_usd: float = WORST_CASE_CALL_RESERVE_USD
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempted_calls: int = 0
    applied_calls: int = 0
    unreported_calls: int = 0
    cutoff_triggered: bool = False
    cutoff_reason: str | None = None

    def __post_init__(self) -> None:
        values = (self.hard_cap_usd, self.operator_reserve_usd, self.call_reserve_usd)
        if any(not math.isfinite(float(value)) or float(value) < 0 for value in values):
            raise ValueError("budget values must be finite and non-negative")
        if not 0 < self.hard_cap_usd <= HARD_BUDGET_CAP_USD:
            raise ValueError(f"hard cap must be greater than zero and no more than ${HARD_BUDGET_CAP_USD:.2f}")
        if self.operator_reserve_usd + self.call_reserve_usd >= self.hard_cap_usd:
            raise ValueError("hard cap must exceed the operator and single-call reserves")

    @property
    def reported_cost_usd(self) -> float:
        return estimated_cost_usd(self.prompt_tokens, self.completion_tokens)

    @property
    def unreported_exposure_usd(self) -> float:
        return self.unreported_calls * self.call_reserve_usd

    @property
    def accounted_exposure_usd(self) -> float:
        return self.reported_cost_usd + self.unreported_exposure_usd

    def can_authorize_call(self) -> bool:
        projected = (
            self.accounted_exposure_usd
            + self.operator_reserve_usd
            + self.call_reserve_usd
        )
        return not self.cutoff_triggered and projected < self.hard_cap_usd

    def reserve_call(self) -> bool:
        """Reserve worst-case exposure before control reaches a network-capable turn."""

        if not self.can_authorize_call():
            return False
        self.unreported_calls += 1
        return True

    def record_turn(self, usage: object, status: object, *, pre_reserved: bool = False) -> None:
        if pre_reserved:
            if self.unreported_calls <= 0:
                raise RuntimeError("cannot settle a call without a matching reservation")
            self.unreported_calls -= 1
        prompt_tokens = 0
        completion_tokens = 0
        if isinstance(usage, dict):
            raw_prompt = usage.get("prompt_tokens")
            raw_completion = usage.get("completion_tokens")
            if isinstance(raw_prompt, int) and not isinstance(raw_prompt, bool) and raw_prompt >= 0:
                prompt_tokens = raw_prompt
            if isinstance(raw_completion, int) and not isinstance(raw_completion, bool) and raw_completion >= 0:
                completion_tokens = raw_completion
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens

        attempted = isinstance(status, dict) and status.get("attempted") is True
        applied = isinstance(status, dict) and status.get("applied") is True
        if attempted:
            self.attempted_calls += 1
            if applied:
                self.applied_calls += 1
            if prompt_tokens + completion_tokens == 0:
                # Failed validation/network responses can still be billable, but
                # the core agent has no trustworthy token count for them.
                self.unreported_calls += 1
        if not self.can_authorize_call():
            self.trigger_cutoff("next call would consume the protected budget reserve")

    def trigger_cutoff(self, reason: str) -> None:
        self.cutoff_triggered = True
        if self.cutoff_reason is None:
            self.cutoff_reason = reason

    def as_dict(self) -> dict:
        return {
            "hard_cap_usd": self.hard_cap_usd,
            "operator_reserve_usd": self.operator_reserve_usd,
            "worst_case_call_reserve_usd": self.call_reserve_usd,
            "input_usd_per_million_tokens": INPUT_USD_PER_MILLION,
            "output_usd_per_million_tokens": OUTPUT_USD_PER_MILLION,
            "reported_prompt_tokens": self.prompt_tokens,
            "reported_completion_tokens": self.completion_tokens,
            "reported_estimated_cost_usd": round(self.reported_cost_usd, 6),
            "unreported_calls": self.unreported_calls,
            "unreported_exposure_reserved_usd": round(self.unreported_exposure_usd, 6),
            "accounted_exposure_usd": round(self.accounted_exposure_usd, 6),
            "attempted_calls": self.attempted_calls,
            "applied_calls": self.applied_calls,
            "cutoff_triggered": self.cutoff_triggered,
            "cutoff_reason": self.cutoff_reason,
            "hard_cap_respected": self.accounted_exposure_usd < self.hard_cap_usd,
        }


class BudgetedTimedAgent:
    """Expose only the Agent contract while enforcing a process-wide API budget."""

    def __init__(self, inner: Agent, budget: BudgetGuard) -> None:
        self.inner = inner
        self.budget = budget
        self.latencies_ms: list[float] = []

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.inner.reset(session_id, user_profile)

    def _disable_enhancement(self, reason: str) -> None:
        self.budget.trigger_cutoff(reason)
        self.inner.enhancer.enabled = False

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        # No target identifier, ground-truth object, or dataset row crosses this
        # boundary. The wrapped Agent receives exactly the official contract.
        if not self.budget.can_authorize_call():
            self._disable_enhancement("next call would consume the protected budget reserve")
        reserved = False
        if self.inner.enhancer.enabled:
            reserved = self.budget.reserve_call()
            if not reserved:
                self._disable_enhancement("next call would consume the protected budget reserve")
        started = time.perf_counter()
        try:
            response = self.inner.respond(session_id, user_message, turn, top_k)
        except Exception:
            # Keep the pre-call reserve: the request may have reached OpenAI even
            # when downstream parsing or evaluation raised before usage settled.
            self.latencies_ms.append((time.perf_counter() - started) * 1000)
            raise
        self.latencies_ms.append((time.perf_counter() - started) * 1000)
        status = self.inner.get_enhancement_status(session_id)
        self.budget.record_turn(response.get("usage"), status, pre_reserved=reserved)
        if self.budget.cutoff_triggered:
            self.inner.enhancer.enabled = False
        return response


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * probability))))
    return ordered[index]


def hybrid_config(rank_blend: float) -> AgentConfig:
    return AgentConfig(
        openai_enhancement=True,
        openai_model=MODEL,
        openai_reasoning_effort=REASONING_EFFORT,
        openai_max_calls=2,
        openai_timeout_seconds=6.0,
        openai_rank_blend=rank_blend,
    )


def _configuration_manifest(config: AgentConfig, budget_usd: float) -> dict:
    values = asdict(config)
    manifest = {
        "agent_config": values,
        "pricing": {
            "input_usd_per_million_tokens": INPUT_USD_PER_MILLION,
            "output_usd_per_million_tokens": OUTPUT_USD_PER_MILLION,
            "long_context_requests_expected": False,
        },
        "budget": {
            "hard_cap_usd": budget_usd,
            "operator_reserve_usd": OPERATOR_RESERVE_USD,
            "worst_case_call_reserve_usd": WORST_CASE_CALL_RESERVE_USD,
        },
        "response_validation_authority": "shopping_copilot.agent.Agent deterministic output validation",
    }
    return {**manifest, "sha256": _sha256_text(_canonical_json(manifest))}


def _plan_evidence(
    selection: HybridSelection,
    config: AgentConfig,
    *,
    dataset_path: str | Path,
    phase: str | None,
    budget_usd: float,
) -> dict:
    selections = selection_manifest(selection)
    configuration = _configuration_manifest(config, budget_usd)
    manifest_hash = _sha256_text(_canonical_json({
        "selection": selections,
        "configuration_sha256": configuration["sha256"],
    }))
    return {
        "schema_version": 2,
        "mode": "dry_run_manifest",
        "network_used": False,
        "network_usage_status": "none_dry_run",
        "evaluation_executed": False,
        "credential_required_for_actual_run": True,
        "requested_phase": phase,
        "requested_phase_role": (
            "tuning_calibration"
            if phase == "calibration"
            else "post_freeze_exploratory_audit_no_tuning_authority"
            if phase == "validation"
            else None
        ),
        "manifest_scope": (
            "The manifest records deterministic selection, hashes, configuration, "
            "and a budget plan. On its own it is not evidence of a model call, scoring "
            "run, token usage, cost, or quality result."
        ),
        "dataset": {
            "path": str(dataset_path),
            "sha256": _file_sha256(dataset_path),
        },
        "selection": selections,
        "configuration": configuration,
        "evidence_manifest_sha256": manifest_hash,
    }


def _write_json(path: str | Path, value: object) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded Terra calibration and post-freeze exploratory audit"
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--phase", choices=("calibration", "validation"))
    parser.add_argument("--calibration-size", type=int, default=DEFAULT_CALIBRATION_SIZE)
    parser.add_argument(
        "--post-freeze-audit-size",
        type=int,
        default=DEFAULT_POST_FREEZE_AUDIT_SIZE,
    )
    parser.add_argument(
        "--validation-size",
        dest="post_freeze_audit_size",
        type=int,
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--rank-blend", type=float, default=0.65)
    parser.add_argument("--budget-usd", type=float, default=HARD_BUDGET_CAP_USD)
    parser.add_argument("--dry-run", action="store_true", help="Select and hash samples without using the network")
    parser.add_argument(
        "--acknowledge-post-freeze-audit",
        dest="acknowledge_post_freeze_audit",
        action="store_true",
        help=(
            "Acknowledge that phase=validation uses a previously inspected holdout subset "
            "for exploratory reporting only and has no tuning authority"
        ),
    )
    parser.add_argument(
        "--acknowledge-locked-validation",
        dest="acknowledge_post_freeze_audit",
        action="store_true",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--output", help="JSON evidence destination")
    args = parser.parse_args(argv)
    if not args.dry_run and args.phase is None:
        parser.error("an actual run requires --phase calibration or --phase validation")
    if args.phase == "validation" and not args.dry_run and not args.acknowledge_post_freeze_audit:
        parser.error(
            "post-freeze exploratory audit requires --acknowledge-post-freeze-audit; "
            "it has no tuning authority"
        )
    if not math.isfinite(args.rank_blend) or not 0 <= args.rank_blend <= 1:
        parser.error("--rank-blend must be between 0 and 1")
    if not math.isfinite(args.budget_usd) or not 0 < args.budget_usd <= HARD_BUDGET_CAP_USD:
        parser.error(f"--budget-usd must be greater than zero and at most {HARD_BUDGET_CAP_USD}")
    if args.budget_usd <= OPERATOR_RESERVE_USD + WORST_CASE_CALL_RESERVE_USD:
        parser.error("--budget-usd is too small for the protected reserves")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    samples = load_jsonl(args.dataset)
    selection = build_selection(
        samples,
        calibration_size=args.calibration_size,
        post_freeze_audit_size=args.post_freeze_audit_size,
    )
    config = hybrid_config(args.rank_blend)
    plan = _plan_evidence(
        selection,
        config,
        dataset_path=args.dataset,
        phase=args.phase,
        budget_usd=args.budget_usd,
    )
    if args.dry_run:
        if args.output:
            _write_json(args.output, plan)
        print(json.dumps(plan, indent=2, sort_keys=True))
        return

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise SystemExit("OPENAI_API_KEY is required for an actual hybrid evaluation; use --dry-run without it")

    selected = (
        selection.calibration
        if args.phase == "calibration"
        else selection.post_freeze_audit
    )
    startup_started = time.perf_counter()
    budget = BudgetGuard(hard_cap_usd=args.budget_usd)
    timed = BudgetedTimedAgent(Agent(args.catalog, config=config), budget)
    startup_seconds = time.perf_counter() - startup_started
    identifiers, categories, products = catalog_index(args.catalog)
    result = evaluate(timed, list(selected), identifiers, categories, products)

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_ram_mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024
    evidence = {
        **plan,
        "mode": "credentialed_evaluation",
        "evaluation_executed": True,
        "network_used": budget.attempted_calls > 0 or budget.unreported_calls > 0,
        "network_usage_status": (
            "confirmed"
            if budget.attempted_calls > 0
            else "possible_unsettled_request"
            if budget.unreported_calls > 0
            else "none"
        ),
        "phase": args.phase,
        "phase_role": (
            "tuning_calibration"
            if args.phase == "calibration"
            else "post_freeze_exploratory_audit_no_tuning_authority"
        ),
        "configuration_change_authorized_by_this_phase": args.phase == "calibration",
        "selected_sample_ids_sha256": _sample_ids_sha256(selected),
        "catalog": {"path": str(args.catalog), "sha256": _file_sha256(args.catalog)},
        "budget": budget.as_dict(),
        "runtime": {
            "python": sys.version.split()[0],
            "startup_seconds": round(startup_seconds, 6),
            "respond_calls": len(timed.latencies_ms),
            "latency_ms_p50": round(statistics.median(timed.latencies_ms), 3),
            "latency_ms_p95": round(_percentile(timed.latencies_ms, 0.95), 3),
            "latency_ms_max": round(max(timed.latencies_ms, default=0.0), 3),
            "peak_ram_mb": round(peak_ram_mb, 3),
        },
        "result": result,
    }
    output_phase = "calibration" if args.phase == "calibration" else "post_freeze_audit"
    output = args.output or f"evaluation/results/hybrid_{output_phase}.json"
    _write_json(output, evidence)
    compact = {
        "phase": args.phase,
        "phase_role": evidence["phase_role"],
        "configuration_change_authorized_by_this_phase": evidence[
            "configuration_change_authorized_by_this_phase"
        ],
        "output": output,
        "sample_count": result["sample_count"],
        "hit_rate_at_10": result["hit_rate_at_10"],
        "mrr": result["mrr"],
        "mttc": result["mttc"],
        "recommended_technical_score": result["recommended_technical_score"],
        "reported_token_usage": result["reported_token_usage"],
        "budget": budget.as_dict(),
    }
    print(json.dumps(compact, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
