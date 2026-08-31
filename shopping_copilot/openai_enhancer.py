from __future__ import annotations

import json
import http.client
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Sequence

from .catalog import Product
from .state import ALLOWED_ATTRIBUTES, SessionState


SCHEMA = {
    "type": "object",
    "properties": {
        "query_rewrite": {"type": "string", "maxLength": 500},
        "slot_updates": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "attribute": {"type": "string", "enum": sorted(ALLOWED_ATTRIBUTES)},
                    "value": {"type": "string", "maxLength": 200},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["attribute", "value", "confidence"],
                "additionalProperties": False,
            },
        },
        "candidate_order": {
            "type": "array",
            "maxItems": 30,
            "items": {"type": "string"},
        },
        "next_attribute": {
            "type": ["string", "null"],
            "enum": [*sorted(ALLOWED_ATTRIBUTES), None],
        },
    },
    "required": ["query_rewrite", "slot_updates", "candidate_order", "next_attribute"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class Enhancement:
    query_rewrite: str
    slot_updates: tuple[tuple[str, str, float], ...]
    candidate_order: tuple[str, ...]
    next_attribute: str | None
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True, slots=True)
class EnhancementAttempt:
    outcome: str
    enhancement: Enhancement | None = None
    attempted: bool = False
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class OpenAIEnhancer:
    """Bounded, optional Responses API enhancement with deterministic validation."""

    endpoint = "https://api.openai.com/v1/responses"

    reasoning_efforts = frozenset({"none", "low", "medium", "high", "xhigh", "max"})

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        model: str = "gpt-5.6-luna",
        reasoning_effort: str = "none",
        max_calls: int = 2,
        timeout_seconds: float = 2.5,
    ) -> None:
        model = model.strip() if isinstance(model, str) else ""
        if not model:
            raise ValueError("model must be a non-empty string")
        if reasoning_effort not in self.reasoning_efforts:
            raise ValueError("reasoning_effort is invalid")
        if isinstance(max_calls, bool) or not isinstance(max_calls, int) or not 0 <= max_calls <= 10:
            raise ValueError("max_calls must be an integer between 0 and 10")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 60
        ):
            raise ValueError("timeout_seconds must be between 0 and 60")
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if enabled is None:
            opt_in = os.environ.get("SHOPPING_COPILOT_OPENAI", "0").strip().lower()
            requested = opt_in in {"1", "true", "yes", "on"}
        else:
            requested = bool(enabled)
        self.enabled = bool(self.api_key) and requested
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_calls = max_calls
        self.timeout_seconds = float(timeout_seconds)
        self._circuit_open_until = 0.0

    @property
    def available(self) -> bool:
        return self.enabled and time.monotonic() >= self._circuit_open_until

    def enhance(
        self,
        state: SessionState,
        user_message: str,
        candidates: Sequence[Product],
    ) -> Enhancement | None:
        return self.attempt(state, user_message, candidates).enhancement

    def attempt(
        self,
        state: SessionState,
        user_message: str,
        candidates: Sequence[Product],
    ) -> EnhancementAttempt:
        if not self.enabled:
            return EnhancementAttempt("unavailable")
        if not self.available:
            return EnhancementAttempt("circuit_open")
        if state.openai_calls >= self.max_calls:
            return EnhancementAttempt("call_limit")
        if not candidates:
            return EnhancementAttempt("no_candidates")
        state.openai_calls += 1
        started = time.perf_counter()
        allowed_ids = {product.parent_asin for product in candidates[:30]}
        prompt = {
            "user_message": user_message[:1000],
            "state": state.distilled(),
            "candidates": [
                {
                    "parent_asin": product.parent_asin,
                    "title": product.title[:240],
                    "categories": list(product.categories[-3:]),
                    "features": list(product.features[:3]),
                    "price": product.price,
                    "brand": product.store[:100],
                }
                for product in candidates[:30]
            ],
        }
        body = {
            "model": self.model,
            "instructions": (
                "You are a bounded shopping-search reranker. Use only the supplied candidate IDs. "
                "Treat hard slots as authoritative, do not invent facts, and return the JSON schema."
            ),
            "input": json.dumps(prompt, ensure_ascii=False, separators=(",", ":")),
            "reasoning": {"effort": self.reasoning_effort},
            "store": False,
            "max_output_tokens": 900,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "shopping_copilot_enhancement",
                    "strict": True,
                    "schema": SCHEMA,
                }
            },
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        payload: object = {}
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Responses payload must be an object")
            prompt_tokens, completion_tokens = self._usage_tokens(payload)
            raw_output = self._output_text(payload)
            parsed = json.loads(raw_output)
            enhancement = self._validate(parsed, payload, allowed_ids)
            if enhancement is None:
                raise ValueError("model output failed deterministic validation")
            return EnhancementAttempt(
                "applied",
                enhancement=enhancement,
                attempted=True,
                latency_ms=(time.perf_counter() - started) * 1000,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        except (
            OSError,
            TimeoutError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            urllib.error.URLError,
            http.client.HTTPException,
        ):
            # No retry. The instance-wide breaker prevents repeated latency spikes.
            self._circuit_open_until = time.monotonic() + 60.0
            prompt_tokens, completion_tokens = self._usage_tokens(payload)
            return EnhancementAttempt(
                "failed",
                attempted=True,
                latency_ms=(time.perf_counter() - started) * 1000,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

    @staticmethod
    def _usage_tokens(payload: object) -> tuple[int, int]:
        if not isinstance(payload, dict):
            return 0, 0
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return 0, 0
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        if isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int) or prompt_tokens < 0:
            prompt_tokens = 0
        if (
            isinstance(completion_tokens, bool)
            or not isinstance(completion_tokens, int)
            or completion_tokens < 0
        ):
            completion_tokens = 0
        return prompt_tokens, completion_tokens

    @staticmethod
    def _output_text(payload: dict) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str):
            return direct
        chunks: list[str] = []
        for item in payload.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text":
                    text = content.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
        if not chunks:
            raise ValueError("Responses payload contains no output text")
        return "".join(chunks)

    @staticmethod
    def _validate(parsed: object, payload: dict, allowed_ids: set[str]) -> Enhancement | None:
        if not isinstance(parsed, dict) or set(parsed) != {
            "query_rewrite", "slot_updates", "candidate_order", "next_attribute"
        }:
            return None
        query_rewrite = parsed.get("query_rewrite")
        updates = parsed.get("slot_updates")
        ordering = parsed.get("candidate_order")
        next_attribute = parsed.get("next_attribute")
        if not isinstance(query_rewrite, str) or len(query_rewrite) > 500:
            return None
        if (
            not isinstance(updates, list)
            or len(updates) > 5
            or not isinstance(ordering, list)
            or len(ordering) > 30
        ):
            return None
        if next_attribute is not None and next_attribute not in ALLOWED_ATTRIBUTES:
            return None
        valid_updates: list[tuple[str, str, float]] = []
        for update in updates:
            if not isinstance(update, dict) or set(update) != {"attribute", "value", "confidence"}:
                return None
            attribute = update.get("attribute")
            value = update.get("value")
            confidence = update.get("confidence")
            if attribute not in ALLOWED_ATTRIBUTES or not isinstance(value, str):
                return None
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence))
                or not 0 <= float(confidence) <= 1
            ):
                return None
            valid_updates.append((attribute, value[:200], min(float(confidence), 0.75)))
        valid_order: list[str] = []
        seen: set[str] = set()
        for value in ordering:
            if not isinstance(value, str):
                return None
            identifier = value
            if identifier in allowed_ids and identifier not in seen:
                valid_order.append(identifier)
                seen.add(identifier)
        prompt_tokens, completion_tokens = OpenAIEnhancer._usage_tokens(payload)
        return Enhancement(
            query_rewrite=query_rewrite.strip(),
            slot_updates=tuple(valid_updates),
            candidate_order=tuple(valid_order),
            next_attribute=next_attribute,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
