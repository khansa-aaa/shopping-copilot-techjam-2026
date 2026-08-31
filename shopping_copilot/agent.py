from __future__ import annotations

import math
import os
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from .catalog import CatalogIndex, terms
from .openai_enhancer import Enhancement, OpenAIEnhancer
from .state import (
    ALLOWED_ATTRIBUTES,
    EnhancementStatus,
    SessionState,
    budget_ceiling,
    normalize_profile,
)


@dataclass(frozen=True, slots=True)
class AgentConfig:
    state_accumulation: bool = True
    structured_retrieval: bool = True
    dense_retrieval: bool = True
    clarification: bool = True
    candidate_rotation: bool = True
    profile_use: bool = False
    openai_enhancement: bool = False
    openai_model: str = "gpt-5.6-luna"
    openai_reasoning_effort: str = "none"
    openai_max_calls: int = 2
    openai_timeout_seconds: float = 2.5
    openai_rank_blend: float = 1.0
    fts_limit: int = 700
    rrf_constant: int = 35
    rerank_limit: int = 100
    broad_candidate_threshold: int = 500
    profile_weight: float = 0.20
    popularity_weight: float = 0.025

    def __post_init__(self) -> None:
        model = self.openai_model.strip() if isinstance(self.openai_model, str) else ""
        if not model:
            raise ValueError("openai_model must be a non-empty string")
        if self.openai_reasoning_effort not in OpenAIEnhancer.reasoning_efforts:
            raise ValueError("openai_reasoning_effort is invalid")
        if (
            isinstance(self.openai_max_calls, bool)
            or not isinstance(self.openai_max_calls, int)
            or not 0 <= self.openai_max_calls <= 10
        ):
            raise ValueError("openai_max_calls must be an integer between 0 and 10")
        if (
            isinstance(self.openai_timeout_seconds, bool)
            or not isinstance(self.openai_timeout_seconds, (int, float))
            or not math.isfinite(float(self.openai_timeout_seconds))
            or not 0 < float(self.openai_timeout_seconds) <= 60
        ):
            raise ValueError("openai_timeout_seconds must be between 0 and 60")
        if (
            isinstance(self.openai_rank_blend, bool)
            or not isinstance(self.openai_rank_blend, (int, float))
            or not math.isfinite(float(self.openai_rank_blend))
            or not 0 <= float(self.openai_rank_blend) <= 1
        ):
            raise ValueError("openai_rank_blend must be between 0 and 1")
        object.__setattr__(self, "openai_model", model)
        object.__setattr__(self, "openai_timeout_seconds", float(self.openai_timeout_seconds))
        object.__setattr__(self, "openai_rank_blend", float(self.openai_rank_blend))

    def with_ablation(self, name: str) -> "AgentConfig":
        mapping = {
            "state": "state_accumulation", "structured": "structured_retrieval",
            "dense": "dense_retrieval", "clarification": "clarification",
            "rotation": "candidate_rotation", "profile": "profile_use",
            "openai": "openai_enhancement",
        }
        field_name = mapping.get(name)
        if field_name is None:
            raise ValueError(f"unknown ablation: {name}")
        return replace(self, **{field_name: False})


class Agent:
    """Headless offline-first shopping copilot implementing the official contract."""

    _indexes: dict[Path, CatalogIndex] = {}
    _index_lock = threading.Lock()

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl", config: AgentConfig | None = None) -> None:
        path = Path(catalog_path).resolve()
        with self._index_lock:
            if path not in self._indexes:
                self._indexes[path] = CatalogIndex(path)
            self.index = self._indexes[path]
        if config is None:
            api_opt_in = os.environ.get("SHOPPING_COPILOT_OPENAI", "0").strip().lower()
            config = replace(AgentConfig(), openai_enhancement=api_opt_in in {"1", "true", "yes", "on"})
        self.config = config
        self.sessions: dict[str, SessionState] = {}
        self.enhancer = OpenAIEnhancer(
            enabled=config.openai_enhancement,
            model=config.openai_model,
            reasoning_effort=config.openai_reasoning_effort,
            max_calls=config.openai_max_calls,
            timeout_seconds=config.openai_timeout_seconds,
        )

    def reset(self, session_id: str, user_profile: dict) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(user_profile, dict):
            raise TypeError("user_profile must be a dict")
        state = SessionState(session_id, normalize_profile(user_profile))
        state.enhancement_status = self._enhancement_status(state, "not_started")
        self.sessions[session_id] = state

    def get_enhancement_status(self, session_id: str) -> dict:
        """Return optional per-turn diagnostics without changing the official response schema."""

        if session_id not in self.sessions:
            raise RuntimeError("reset must be called before reading enhancement status")
        return self.sessions[session_id].enhancement_status.as_dict()

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        if session_id not in self.sessions:
            raise RuntimeError("reset must be called before respond")
        if not isinstance(user_message, str):
            raise TypeError("user_message must be a string")
        if not isinstance(top_k, int) or not 1 <= top_k <= 10:
            raise ValueError("top_k must be an integer between 1 and 10")
        state = self.sessions[session_id]
        if not self.config.state_accumulation and turn > 1:
            state = SessionState(
                session_id,
                state.user_profile,
                last_recommendations=state.last_recommendations,
                openai_calls=state.openai_calls,
                prompt_tokens=state.prompt_tokens,
                completion_tokens=state.completion_tokens,
                enhancement_status=state.enhancement_status,
            )
            self.sessions[session_id] = state
        state.start_turn(user_message, turn)
        prompt_tokens_before = state.prompt_tokens
        completion_tokens_before = state.completion_tokens

        ranked, candidate_count, separation, eligible = self._retrieve(state, user_message)
        if not ranked:
            ranked = list(range(min(len(self.index.products), max(top_k, 10))))
        ranked = self._rotate(ranked, state, top_k)
        broad = self._is_over_general(state, candidate_count, separation)
        if broad:
            ranked = self._diversify(ranked, top_k)

        enhancement = None
        if self.config.openai_enhancement:
            rerankable = [index for index in ranked[:30] if index in eligible]
            attempt = self.enhancer.attempt(
                state, user_message, [self.index.products[index] for index in rerankable]
            )
            state.prompt_tokens += attempt.prompt_tokens
            state.completion_tokens += attempt.completion_tokens
            enhancement = attempt.enhancement
            if enhancement is not None:
                ranked = self._apply_enhancement(ranked, state, enhancement, eligible)
            state.enhancement_status = self._enhancement_status(
                state,
                attempt.outcome,
                attempted=attempt.attempted,
                applied=enhancement is not None,
                latency_ms=attempt.latency_ms,
                prompt_tokens=attempt.prompt_tokens,
                completion_tokens=attempt.completion_tokens,
            )
        else:
            state.enhancement_status = self._enhancement_status(state, "disabled")

        recommendations = [
            {"parent_asin": self.index.products[index].parent_asin} for index in ranked[:top_k]
        ]
        ask_attribute = self._next_attribute(state, ranked[:100], broad)
        known_attributes = {
            attribute for attribute in ALLOWED_ATTRIBUTES if state.active_evidence(attribute)
        }
        if enhancement and enhancement.next_attribute and turn < 10:
            proposed_attribute = enhancement.next_attribute
            if proposed_attribute not in state.no_preferences and proposed_attribute not in known_attributes:
                ask_attribute = proposed_attribute
        if turn >= 10 or not self.config.clarification:
            ask_attribute = None
        response = {
            "message": self._message(ask_attribute, broad, bool(recommendations)),
            "ask_attribute": ask_attribute,
            "recommendations": recommendations,
            "usage": {
                "prompt_tokens": state.prompt_tokens - prompt_tokens_before,
                "completion_tokens": state.completion_tokens - completion_tokens_before,
            },
        }
        state.last_recommendations = tuple(item["parent_asin"] for item in recommendations)
        return self._validate_response(response, top_k)

    def _retrieve(
        self, state: SessionState, user_message: str
    ) -> tuple[list[int], int, float, set[int]]:
        accumulated = state.query_text(include_profile=False)
        query = accumulated if self.config.state_accumulation else user_message
        if not query.strip():
            query = user_message
        profile_query = " ".join(state.profile_priors) if self.config.profile_use else ""
        routes: dict[str, list[int]] = {
            "exact": self.index.fts(query, limit=350, conjunctive=True),
            "bm25": self.index.fts(query, limit=self.config.fts_limit),
        }
        categories = " ".join(item.value for item in state.active_evidence("category"))
        if categories:
            routes["category"] = self.index.fts(categories, limit=self.config.fts_limit)
        if profile_query:
            routes["profile"] = self.index.fts(f"{categories} {profile_query}", limit=260)

        structured_pool: set[int] = set()
        hard_filters: list[tuple[float, set[int], str]] = []
        if self.config.structured_retrieval:
            for attribute in ("material", "color", "brand"):
                for evidence in state.active_evidence(attribute):
                    candidates = self.index.facet_candidates(attribute, evidence.value)
                    if candidates:
                        structured_pool.update(candidates)
                        if evidence.hard and evidence.confidence >= 0.75:
                            hard_filters.append((evidence.confidence, candidates, attribute))
            if structured_pool:
                query_terms = set(terms(query))
                lexical_pool = {
                    index for route in routes.values() for index in route
                    if index in structured_pool
                }
                rank_pool = lexical_pool or set(sorted(structured_pool)[:1500])
                routes["structured"] = sorted(
                    rank_pool,
                    key=lambda index: (
                        -len(query_terms.intersection(self.index.token_set(index))),
                        -self.index.products[index].average_rating,
                        self.index.products[index].parent_asin,
                    ),
                )[:700]

        all_candidates = {index for values in routes.values() for index in values}
        if not all_candidates:
            all_candidates.update(range(len(self.index.products)))
        filtered = set(all_candidates)
        for _, constraint, _ in sorted(hard_filters, key=lambda item: -item[0]):
            narrowed = filtered.intersection(constraint)
            if narrowed:
                filtered = narrowed
        budget_filters = [
            (evidence.confidence, budget_ceiling(evidence))
            for evidence in state.active_evidence("budget") if evidence.hard
        ]
        for _, ceiling in sorted(budget_filters, reverse=True):
            if ceiling is None:
                continue
            narrowed = {
                index for index in filtered
                if self.index.products[index].price is not None
                and self.index.products[index].price <= ceiling * 1.12
            }
            if narrowed:
                filtered = narrowed
        for name, values in tuple(routes.items()):
            selected = [index for index in values if index in filtered]
            if selected:
                routes[name] = selected

        dense_pool = set(filtered)
        if len(dense_pool) > 1500:
            dense_pool = set(sorted(dense_pool)[:1500])
        if self.config.dense_retrieval and dense_pool:
            scores = self.index.dense_scores(query, dense_pool)
            routes["dense"] = sorted(scores, key=lambda index: (-scores[index], self.index.ids[index]))[:600]

        weights = {
            "exact": 2.30, "structured": 1.75, "bm25": 1.45, "dense": 1.05,
            "category": 0.75, "profile": self.config.profile_weight,
        }
        fused: defaultdict[int, float] = defaultdict(float)
        provenance: defaultdict[int, set[str]] = defaultdict(set)
        for route_name, ranking in routes.items():
            for rank, index in enumerate(ranking, 1):
                fused[index] += weights.get(route_name, 1.0) / (self.config.rrf_constant + rank)
                provenance[index].add(route_name)
        ordered = sorted(fused, key=lambda index: (-fused[index], self.index.ids[index]))
        shortlist = ordered[:max(self.config.rerank_limit, 100)]
        reranked = self._rerank(shortlist, fused, provenance, state, query)
        selected = set(reranked)
        reranked.extend(index for index in ordered if index not in selected)
        separation = 0.0
        if len(reranked) >= 10:
            separation = self._final_score(reranked[0], fused, query) - self._final_score(reranked[9], fused, query)
        candidate_count = len(filtered)
        if not hard_filters and not budget_filters and categories:
            category_matches = self.index.facet_candidates("category", categories)
            if category_matches:
                candidate_count = max(candidate_count, len(category_matches))
        return reranked, candidate_count, separation, filtered

    def _rerank(self, candidates, fused, provenance, state, query) -> list[int]:
        max_fused = max((fused[index] for index in candidates), default=1.0) or 1.0
        query_terms = set(terms(query))
        evidence = state.active_evidence()

        def score(index: int) -> tuple[float, str]:
            product = self.index.products[index]
            product_terms = self.index.token_set(index)
            overlap = len(query_terms.intersection(product_terms)) / max(1, len(query_terms))
            title_terms = set(terms(product.title))
            title_overlap = len(query_terms.intersection(title_terms)) / max(1, len(query_terms))
            phrase = 0.0
            for item in evidence:
                normalized = re.sub(r"\s+", " ", item.value).strip().lower()
                if normalized and normalized in product.search_text:
                    phrase += (0.14 if item.hard else 0.06) * item.confidence
            popularity = self.config.popularity_weight * (
                max(0.0, min(product.average_rating, 5.0)) / 5.0
                + min(math.log1p(product.rating_number) / 12.0, 1.0)
            )
            total = (
                0.50 * fused.get(index, 0.0) / max_fused + 0.29 * overlap
                + 0.12 * title_overlap + phrase + 0.015 * len(provenance.get(index, ())) + popularity
            )
            return -total, product.parent_asin
        return sorted(candidates, key=score)

    def _final_score(self, index: int, fused: dict[int, float], query: str) -> float:
        query_terms = set(terms(query))
        overlap = len(query_terms.intersection(self.index.token_set(index))) / max(1, len(query_terms))
        return fused.get(index, 0.0) + overlap

    def _rotate(self, ranking: list[int], state: SessionState, top_k: int) -> list[int]:
        if not self.config.candidate_rotation or not state.rejected:
            return ranking
        unseen = [index for index in ranking if self.index.ids[index] not in state.rejected]
        seen = [index for index in ranking if self.index.ids[index] in state.rejected]
        return unseen + seen if len(unseen) >= top_k else ranking

    def _is_over_general(self, state: SessionState, candidate_count: int, separation: float) -> bool:
        hard = [item for item in state.active_evidence() if item.hard and item.source != "category"]
        return not hard and (candidate_count > self.config.broad_candidate_threshold or separation < 0.025)

    def _diversify(self, ranking: Sequence[int], top_k: int) -> list[int]:
        selected: list[int] = []
        deferred: list[int] = []
        groups: set[tuple[str, str]] = set()
        for index in ranking:
            product = self.index.products[index]
            category = product.categories[-1].casefold() if product.categories else ""
            key = (category, product.store.casefold())
            if key not in groups and len(selected) < top_k:
                groups.add(key)
                selected.append(index)
            else:
                deferred.append(index)
        return selected + deferred

    def _next_attribute(self, state: SessionState, candidates: Sequence[int], broad: bool) -> str | None:
        if state.turn >= 10 or not self.config.clarification:
            return None
        if broad and "other" not in state.no_preferences:
            return "other"
        known = {name for name in state.slots if state.active_evidence(name)}
        best_attribute = None
        best_gain = -1.0
        for attribute in ("material", "color", "brand", "category"):
            if attribute in known or attribute in state.no_preferences:
                continue
            distribution = self.index.distribution(candidates, attribute)
            total = sum(distribution.values())
            if total <= 1:
                continue
            entropy = -sum((count / total) * math.log2(count / total) for count in distribution.values())
            gain = entropy * min(1.0, total / max(1, len(candidates)))
            if gain > best_gain:
                best_gain, best_attribute = gain, attribute
        if best_attribute and best_gain >= 0.35:
            return best_attribute
        for fallback in ("feature", "use_case", "style", "size", "budget", "other"):
            if fallback not in known and fallback not in state.no_preferences:
                return fallback
        return None

    @staticmethod
    def _message(attribute: str | None, broad: bool, has_recommendations: bool) -> str:
        if attribute == "other" and broad:
            return (
                "I’ve started with a diverse shortlist. What matters most—product type or use, "
                "material or color, fit or size, brand, or budget?"
            )
        questions = {
            "category": "Which product type should I narrow this to?",
            "material": "Do you have a material preference?", "color": "Which color would you prefer?",
            "size": "What size or fit should I prioritize?", "style": "Which style or fit do you prefer?",
            "brand": "Do you have a preferred brand?", "budget": "What budget should I stay within?",
            "feature": "Which feature matters most?", "use_case": "What will you mainly use it for?",
            "other": "What other requirement would help me narrow this down?",
        }
        if attribute in questions:
            return ("I’ve refined the shortlist. " if has_recommendations else "") + questions[attribute]
        return "Here are the best matches from the current preferences."

    def _apply_enhancement(
        self,
        ranking: list[int],
        state: SessionState,
        enhancement: Enhancement,
        allowed_rerank: set[int],
    ) -> list[int]:
        for attribute, value, confidence in enhancement.slot_updates:
            state.add_evidence(attribute, value, confidence=confidence, hard=False, source="openai")
        if enhancement.query_rewrite:
            state.add_evidence(
                "feature", enhancement.query_rewrite,
                confidence=0.55, hard=False, source="openai_query_rewrite",
            )
        ranking_set = set(ranking)
        preferred: list[int] = []
        seen: set[int] = set()
        for value in enhancement.candidate_order:
            index = self.index.id_to_index.get(value)
            if index is None or index not in ranking_set or index not in allowed_rerank or index in seen:
                continue
            preferred.append(index)
            seen.add(index)
        return self._blend_ranking(ranking, preferred, self.config.openai_rank_blend)

    def _blend_ranking(self, ranking: list[int], preferred: list[int], weight: float) -> list[int]:
        if not preferred or weight <= 0:
            return ranking
        if weight >= 1:
            selected = set(preferred)
            return preferred + [index for index in ranking if index not in selected]
        base_rank = {index: rank for rank, index in enumerate(ranking, 1)}
        selected = set(preferred)
        model_order = preferred + [index for index in ranking if index not in selected]
        model_rank = {index: rank for rank, index in enumerate(model_order, 1)}
        constant = self.config.rrf_constant

        def score(index: int) -> tuple[float, int]:
            value = (1.0 - weight) / (constant + base_rank[index])
            value += weight / (constant + model_rank[index])
            return -value, base_rank[index]

        return sorted(ranking, key=score)

    def _enhancement_status(
        self,
        state: SessionState,
        outcome: str,
        *,
        attempted: bool = False,
        applied: bool = False,
        latency_ms: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> EnhancementStatus:
        return EnhancementStatus(
            turn=state.turn,
            outcome=outcome,
            enabled=bool(getattr(self.enhancer, "enabled", False)),
            attempted=attempted,
            applied=applied,
            model=self.config.openai_model,
            reasoning_effort=self.config.openai_reasoning_effort,
            calls_used=state.openai_calls,
            max_calls=self.config.openai_max_calls,
            timeout_seconds=self.config.openai_timeout_seconds,
            rank_blend=self.config.openai_rank_blend,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _validate_response(self, response: dict, top_k: int) -> dict:
        if set(response) != {"message", "ask_attribute", "recommendations", "usage"}:
            raise ValueError("response has unexpected fields")
        if not isinstance(response["message"], str):
            raise TypeError("message must be a string")
        if response["ask_attribute"] is not None and response["ask_attribute"] not in ALLOWED_ATTRIBUTES:
            raise ValueError("ask_attribute is invalid")
        recommendations = response["recommendations"]
        if not isinstance(recommendations, list) or len(recommendations) > top_k:
            raise ValueError("recommendations must be a bounded list")
        seen: set[str] = set()
        for item in recommendations:
            if not isinstance(item, dict) or set(item) != {"parent_asin"}:
                raise ValueError("recommendation must contain only parent_asin")
            identifier = item["parent_asin"]
            if not isinstance(identifier, str) or identifier not in self.index.id_to_index or identifier in seen:
                raise ValueError("recommendation identifier is invalid or duplicated")
            seen.add(identifier)
        usage = response["usage"]
        if not isinstance(usage, dict) or set(usage) != {"prompt_tokens", "completion_tokens"}:
            raise ValueError("usage has invalid shape")
        if any(not isinstance(value, int) or value < 0 for value in usage.values()):
            raise ValueError("usage values must be non-negative integers")
        return response
