from __future__ import annotations

import copy
import re
import threading
import time
import uuid
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shopping_copilot.agent import Agent, AgentConfig
from shopping_copilot.catalog import COLORS, MATERIALS, Product, terms
from shopping_copilot.state import budget_ceiling

from .marketplaces import MARKETPLACES, marketplace_payload


MAX_TURNS = 10
TOP_K = 10
SESSION_TTL_SECONDS = 2 * 60 * 60
MAX_SESSIONS = 64


class ServiceError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        expected_next_turn: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.expected_next_turn = expected_next_turn

    def payload(self) -> dict[str, dict[str, Any]]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.expected_next_turn is not None:
            error["expected_next_turn"] = self.expected_next_turn
        return {"error": error}


@dataclass(slots=True)
class CachedRequest:
    message: str
    expected_turn: int
    response: dict | None = None
    agent_response: dict | None = None
    latency_ms: float = 0.0


@dataclass(slots=True)
class WebSession:
    session_id: str
    mode: str
    marketplace: str
    turn: int = 0
    created_at: float = field(default_factory=time.monotonic)
    last_accessed_at: float = field(default_factory=time.monotonic)
    requests: dict[str, CachedRequest] = field(default_factory=dict)
    faulted: bool = False


class ShoppingService:
    def __init__(self, catalog_path: str | Path) -> None:
        self.catalog_path = Path(catalog_path).resolve()
        self.status = "starting"
        self.startup_error: str | None = None
        self.startup_seconds: float | None = None
        self.offline_agent: Agent | None = None
        self.hybrid_agent: Agent | None = None
        self.sessions: OrderedDict[str, WebSession] = OrderedDict()
        self.creation_requests: dict[str, tuple[tuple[Any, ...], dict]] = {}
        self.lock = threading.RLock()
        self.started_at = time.perf_counter()

    def initialize(self) -> None:
        with self.lock:
            if self.status == "ready":
                return
            self.status = "starting"
        started = time.perf_counter()
        try:
            offline = Agent(self.catalog_path, config=AgentConfig())
            hybrid = Agent(
                self.catalog_path,
                config=AgentConfig(
                    profile_use=True,
                    openai_enhancement=True,
                    openai_model="gpt-5.6-terra",
                    openai_reasoning_effort="low",
                    openai_max_calls=10,
                    openai_timeout_seconds=6.0,
                    openai_rank_blend=0.65,
                ),
            )
        except Exception as exc:
            with self.lock:
                self.status = "failed"
                self.startup_error = type(exc).__name__
            return
        with self.lock:
            self.offline_agent = offline
            self.hybrid_agent = hybrid
            self.startup_seconds = time.perf_counter() - started
            self.status = "ready"
            self.startup_error = None

    @property
    def hybrid_available(self) -> bool:
        """Report the capability actually loaded by this server process.

        OpenAI credentials are read when the hybrid agent is initialized.  Reading
        the environment again here could advertise a key that was added after
        startup even though the already-created enhancer cannot use it.
        """

        return bool(
            self.status == "ready"
            and self.hybrid_agent is not None
            # Consent follows the stable, key-loaded capability. A transient
            # circuit breaker may recover during an existing web session.
            and self.hybrid_agent.enhancer.enabled
        )

    def health(self) -> dict:
        with self.lock:
            catalog_count = 0
            if self.offline_agent is not None:
                catalog_count = len(self.offline_agent.index.products)
            return {
                "status": self.status,
                "catalog_count": catalog_count,
                "max_turns": MAX_TURNS,
                "agent_contract": "reset/respond-v1",
                "hybrid_available": self.hybrid_available,
                "hybrid_model": "gpt-5.6-terra",
                "startup_seconds": None if self.startup_seconds is None else round(self.startup_seconds, 3),
                "marketplaces": marketplace_payload(),
            }

    def create_session(
        self,
        request_id: str,
        *,
        mode: str,
        marketplace: str,
        preference_tags: list[str],
    ) -> dict:
        fingerprint = (mode, marketplace, tuple(preference_tags))
        with self.lock:
            self._require_ready()
            self._purge_expired()
            cached = self.creation_requests.get(request_id)
            if cached is not None:
                if cached[0] != fingerprint:
                    raise ServiceError(409, "IDEMPOTENCY_CONFLICT", "This request ID was already used with different session settings.")
                cached_session_id = cached[1].get("session_id")
                if cached_session_id in self.sessions:
                    return copy.deepcopy(cached[1])
                # A deleted, expired, or capacity-evicted session must never be
                # resurrected by an otherwise valid idempotency replay.
                self.creation_requests.pop(request_id, None)
            while len(self.sessions) >= MAX_SESSIONS:
                old_id, old_session = self.sessions.popitem(last=False)
                self._agent_for(old_session.mode).sessions.pop(old_id, None)
            session_id = uuid.uuid4().hex
            agent = self._agent_for(mode)
            agent.reset(session_id, {"preference_tags": preference_tags})
            session = WebSession(session_id=session_id, mode=mode, marketplace=marketplace)
            self.sessions[session_id] = session
            response = {
                "session_id": session_id,
                "turn": 0,
                "max_turns": MAX_TURNS,
                "status": "active",
                "mode": mode,
                "marketplace": marketplace,
                "expert_state": self._expert_state(agent, session_id, None, 0.0),
            }
            self.creation_requests[request_id] = (fingerprint, copy.deepcopy(response))
            if len(self.creation_requests) > MAX_SESSIONS * 2:
                self.creation_requests.pop(next(iter(self.creation_requests)))
            return response

    def respond(
        self,
        session_id: str,
        *,
        request_id: str,
        message: str,
        expected_turn: int,
    ) -> dict:
        cleaned = re.sub(r"\s+", " ", message).strip()
        with self.lock:
            self._require_ready()
            self._purge_expired()
            session = self.sessions.get(session_id)
            if session is None:
                raise ServiceError(404, "SESSION_NOT_FOUND", "This shopping session is no longer available. Start a new one.")
            if session.faulted:
                raise ServiceError(409, "SESSION_FAULTED", "This session could not recover from an earlier error. Start a new one.")
            cached = session.requests.get(request_id)
            if cached is not None:
                if cached.message != cleaned or cached.expected_turn != expected_turn:
                    raise ServiceError(409, "IDEMPOTENCY_CONFLICT", "This request ID was already used for another message.")
                if cached.response is None:
                    if cached.agent_response is None:
                        session.faulted = True
                        raise ServiceError(409, "SESSION_FAULTED", "This session could not recover from an earlier error. Start a new one.")
                    agent = self._agent_for(session.mode)
                    try:
                        response = self._assemble_response(
                            agent,
                            session,
                            cached.agent_response,
                            cached.latency_ms,
                            expected_turn,
                        )
                        self._commit_response(session, request_id, cached, response, expected_turn)
                    except Exception as exc:
                        raise ServiceError(
                            500,
                            "ADAPTER_FAILURE_RETRYABLE",
                            "The result was preserved, but the web view could not be assembled. Retry the same turn safely.",
                        ) from exc
                replay = copy.deepcopy(cached.response)
                if replay is None:
                    raise ServiceError(500, "ADAPTER_FAILURE_RETRYABLE", "The preserved result is not ready yet. Retry the same turn safely.")
                replay["meta"]["idempotency_replay"] = True
                return replay
            if any(item.response is None for item in session.requests.values()):
                raise ServiceError(
                    409,
                    "PENDING_REQUEST_RETRY_REQUIRED",
                    "An earlier result is preserved but unfinished. Retry that same request before sending another message.",
                    expected_next_turn=session.turn + 1,
                )
            next_turn = session.turn + 1
            if session.turn >= MAX_TURNS:
                raise ServiceError(409, "TURN_LIMIT_REACHED", "This ten-turn session is complete. Start a new search to continue.")
            if expected_turn != next_turn:
                raise ServiceError(
                    409,
                    "TURN_CONFLICT",
                    f"The next message must be turn {next_turn}.",
                    expected_next_turn=next_turn,
                )
            agent = self._agent_for(session.mode)
            previous_state = copy.deepcopy(agent.sessions[session_id])
            started = time.perf_counter()
            try:
                agent_response = agent.respond(session_id, cleaned, next_turn, TOP_K)
            except Exception as exc:
                agent.sessions[session_id] = previous_state
                raise ServiceError(500, "AGENT_FAILURE_RESET_REQUIRED", "The search engine could not complete that turn. Your prior session state was preserved.") from exc

            latency_ms = (time.perf_counter() - started) * 1000
            cached = CachedRequest(
                cleaned,
                expected_turn,
                agent_response=copy.deepcopy(agent_response),
                latency_ms=latency_ms,
            )
            # Persist the authoritative Agent result before presentation work.
            # A same-ID retry can resume without repeating a billable model call
            # if the deterministic web adapter ever fails.
            session.requests[request_id] = cached
            try:
                response = self._assemble_response(agent, session, agent_response, latency_ms, next_turn)
                self._commit_response(session, request_id, cached, response, next_turn)
            except Exception as exc:
                raise ServiceError(
                    500,
                    "ADAPTER_FAILURE_RETRYABLE",
                    "The result was preserved, but the web view could not be assembled. Retry the same turn safely.",
                ) from exc
            return response

    def _assemble_response(
        self,
        agent: Agent,
        session: WebSession,
        agent_response: dict,
        latency_ms: float,
        turn: int,
    ) -> dict:
        products = self._display_products(agent, session.session_id, agent_response, session.marketplace)
        quick_replies = self._quick_replies(agent_response.get("ask_attribute"), products)
        expert_state = self._expert_state(agent, session.session_id, agent_response, latency_ms)
        return {
            "session_id": session.session_id,
            "turn": turn,
            "max_turns": MAX_TURNS,
            "status": "complete" if turn >= MAX_TURNS else "active",
            "agent_response": agent_response,
            "products": products,
            "experience": {
                "quick_replies": quick_replies,
                "snapshot_disclosure": "Fixed 50,000-item TechJam catalog snapshot; not live Amazon inventory.",
                "amazon_disclosure": "Verify the current listing on Amazon. No purchase happens in this demo.",
            },
            "expert_state": expert_state,
            "meta": {
                "latency_ms": round(latency_ms, 2),
                "requested_mode": session.mode,
                "used_mode": expert_state["enhancement"]["used_mode"],
                "fallback_reason": expert_state["enhancement"]["fallback_reason"],
                "idempotency_replay": False,
                "estimated_cost_usd": self._estimated_cost(agent_response.get("usage", {}), session.mode),
            },
        }

    def _commit_response(
        self,
        session: WebSession,
        request_id: str,
        cached: CachedRequest,
        response: dict,
        turn: int,
    ) -> None:
        cached.response = copy.deepcopy(response)
        session.turn = turn
        session.last_accessed_at = time.monotonic()
        self.sessions.move_to_end(session.session_id)
        session.requests[request_id] = cached

    def delete_session(self, session_id: str) -> None:
        with self.lock:
            session = self.sessions.pop(session_id, None)
            if session is not None:
                self._agent_for(session.mode).sessions.pop(session_id, None)

    def _require_ready(self) -> None:
        if self.status != "ready":
            message = "The product catalog is still being indexed." if self.status == "starting" else "The product catalog could not be initialized."
            raise ServiceError(503, "ENGINE_NOT_READY", message)

    def _agent_for(self, mode: str) -> Agent:
        agent = self.hybrid_agent if mode == "hybrid" else self.offline_agent
        if agent is None:
            raise ServiceError(503, "ENGINE_NOT_READY", "The product catalog is still being indexed.")
        return agent

    def _purge_expired(self) -> None:
        cutoff = time.monotonic() - SESSION_TTL_SECONDS
        expired = [session_id for session_id, session in self.sessions.items() if session.last_accessed_at < cutoff]
        for session_id in expired:
            session = self.sessions.pop(session_id)
            self._agent_for(session.mode).sessions.pop(session_id, None)

    def _display_products(self, agent: Agent, session_id: str, response: dict, marketplace_code: str) -> list[dict]:
        marketplace = MARKETPLACES[marketplace_code]
        state = agent.sessions[session_id]
        products: list[dict] = []
        for rank, recommendation in enumerate(response["recommendations"], 1):
            parent_asin = recommendation["parent_asin"]
            product = agent.index.products[agent.index.id_to_index[parent_asin]]
            products.append({
                "rank": rank,
                "parent_asin": parent_asin,
                "title": product.title[:240] or "Untitled catalog item",
                "price": product.price,
                "store": product.store[:100] or None,
                "categories": list(product.categories[-3:]),
                "category": product.categories[-1][:120] if product.categories else "Uncategorized",
                "features": [value[:180] for value in product.features[:3]],
                "details": {key[:80]: value[:180] for key, value in product.details[:6]},
                "average_rating": round(product.average_rating, 2),
                "rating_number": product.rating_number,
                "match_reasons": self._match_reasons(product, state),
                "amazon_url": marketplace.search_url(parent_asin),
                "data_source": "techjam_catalog_snapshot",
                "is_live": False,
            })
        return products

    @staticmethod
    def _match_reasons(product: Product, state: Any) -> list[str]:
        reasons: list[str] = []

        def add_reason(reason: str) -> None:
            if reason.casefold() not in {item.casefold() for item in reasons}:
                reasons.append(reason)

        for evidence in state.active_evidence():
            value = evidence.value.strip()
            if not value:
                continue
            if evidence.source == "category":
                add_reason(f"Matches your {value[:70]} category")
            elif value.casefold() in product.search_text:
                prefix = "Must-have: " if evidence.hard else "Preference: "
                add_reason(f"{prefix}{value[:60]} appears in the catalog details")
            elif evidence.source != "category":
                evidence_terms = set(terms(value))
                if evidence_terms and len(evidence_terms.intersection(set(terms(product.search_text)))) / len(evidence_terms) >= 0.6:
                    add_reason(f"Strong overlap with {value[:70]}")
            if evidence.source != "category" and budget_ceiling(evidence) is not None and product.price is not None:
                ceiling = budget_ceiling(evidence)
                if ceiling is not None and product.price <= ceiling * 1.12:
                    add_reason(f"Within your approximate ${ceiling:g} budget")
            if len(reasons) >= 2:
                break
        if not reasons and product.categories:
            add_reason(f"Strong catalog match in {product.categories[-1][:80]}")
        if len(reasons) < 2 and product.average_rating >= 4.2 and product.rating_number:
            add_reason(f"{product.average_rating:.1f} catalog rating from {product.rating_number:,} reviews")
        return reasons[:2]

    @staticmethod
    def _quick_replies(attribute: str | None, products: list[dict]) -> list[dict[str, str]]:
        if not attribute:
            return []
        values: list[tuple[str, str]] = []
        if attribute == "category":
            seen: set[str] = set()
            for product in products:
                label = product["category"]
                if label.casefold() not in seen:
                    values.append((label[:32], f"I'm looking for {label[:80]}."))
                    seen.add(label.casefold())
                if len(values) >= 3:
                    break
        elif attribute == "brand":
            counts = Counter(product["store"] for product in products if product["store"])
            values = [
                (brand[:32], f"For that, what matters is: brand {brand[:80]}.")
                for brand, _ in counts.most_common(3)
            ]
        elif attribute == "material":
            corpus = " ".join(" ".join(product["features"]) for product in products).casefold()
            found = [value for value in MATERIALS if re.search(rf"\b{re.escape(value)}\b", corpus)]
            for value in (found or ["cotton", "leather", "wool"])[:3]:
                values.append((value.title(), f"For that, what matters is: {value}."))
        elif attribute == "color":
            corpus = " ".join(product["title"] + " " + " ".join(product["features"]) for product in products).casefold()
            found = list(dict.fromkeys(value for value in COLORS if re.search(rf"\b{re.escape(value)}\b", corpus)))
            for value in (found or ["black", "blue", "white"])[:3]:
                values.append((value.title(), f"For that, what matters is: {value}."))
        elif attribute == "budget":
            values = [
                ("Under $25", "For that, what matters is: budget under $25."),
                ("Under $50", "For that, what matters is: budget under $50."),
                ("Under $100", "For that, what matters is: budget under $100."),
            ]
        elif attribute == "size":
            values = [
                ("Small", "For that, what matters is: size small."),
                ("Medium", "For that, what matters is: size medium."),
                ("Wide fit", "For that, what matters is: wide fit sizing."),
            ]
        elif attribute == "style":
            values = [(label, f"For that, what matters is: {label.lower()} style.") for label in ("Casual", "Athletic", "Classic")]
        elif attribute == "use_case":
            values = [(label, f"For that, what matters is: {label.lower()} use.") for label in ("Work", "Travel", "Outdoor")]
        elif attribute == "feature":
            values = [(label, f"For that, what matters is: {label.lower()}.") for label in ("Lightweight", "Breathable", "Pockets")]
        else:
            values = [
                ("Comfort", "For that, what matters is: comfort."),
                ("Lightweight", "For that, what matters is: lightweight construction."),
                ("Under $50", "For that, what matters is: budget under $50."),
            ]
        values.append(("No preference", f"I don't have an additional preference for {attribute}."))
        return [{"label": label, "message": message} for label, message in values[:4]]

    def _expert_state(self, agent: Agent, session_id: str, response: dict | None, latency_ms: float) -> dict:
        state = agent.sessions[session_id]
        distilled = state.distilled()
        active = state.active_evidence()
        enhancement = agent.get_enhancement_status(session_id)
        if agent.config.openai_enhancement:
            used_mode = "hybrid" if enhancement["applied"] else "offline_fallback"
            fallback_reason = None if enhancement["applied"] else enhancement["outcome"].replace("_", " ")
        else:
            used_mode = "offline"
            fallback_reason = None
        return {
            **distilled,
            "hard_constraints": [item.value for item in active if item.hard],
            "soft_preferences": [item.value for item in active if not item.hard],
            "previously_shown_count": len(state.rejected),
            "openai_calls": state.openai_calls,
            "next_attribute": None if response is None else response.get("ask_attribute"),
            "latency_ms": round(latency_ms, 2),
            "enhancement": {
                **enhancement,
                "requested": agent.config.openai_enhancement,
                "status": enhancement["outcome"],
                "used_mode": used_mode,
                "fallback_reason": fallback_reason,
            },
            "retrieval": ["Exact text", "FTS5 keyword", "Structured facets", "256D catalog hash", "Weighted rank fusion"],
        }

    @staticmethod
    def _estimated_cost(usage: dict, mode: str) -> float:
        if mode != "hybrid":
            return 0.0
        prompt = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0
        completion = usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
        if not isinstance(prompt, int) or not isinstance(completion, int):
            return 0.0
        return round(prompt * 2.0 / 1_000_000 + completion * 12.0 / 1_000_000, 6)
