from __future__ import annotations

import json
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


class OpenAIEnhancer:
    """Bounded, optional Responses API enhancement with deterministic validation."""

    endpoint = "https://api.openai.com/v1/responses"

    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        opt_in = os.environ.get("SHOPPING_COPILOT_OPENAI", "0").strip().lower()
        self.enabled = bool(self.api_key) and opt_in in {"1", "true", "yes", "on"}
        self.model = "gpt-5.6-luna"
        self.timeout_seconds = 2.5
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
        if not self.available or state.openai_calls >= 2 or not candidates:
            return None
        state.openai_calls += 1
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
            "reasoning": {"effort": "none"},
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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            raw_output = self._output_text(payload)
            parsed = json.loads(raw_output)
            enhancement = self._validate(parsed, payload, allowed_ids)
            if enhancement is None:
                raise ValueError("model output failed deterministic validation")
            return enhancement
        except (OSError, TimeoutError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
            # No retry. The instance-wide breaker prevents repeated latency spikes.
            self._circuit_open_until = time.monotonic() + 60.0
            return None

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
        if not isinstance(parsed, dict):
            return None
        query_rewrite = parsed.get("query_rewrite")
        updates = parsed.get("slot_updates")
        ordering = parsed.get("candidate_order")
        next_attribute = parsed.get("next_attribute")
        if not isinstance(query_rewrite, str) or len(query_rewrite) > 500:
            return None
        if not isinstance(updates, list) or not isinstance(ordering, list):
            return None
        if next_attribute is not None and next_attribute not in ALLOWED_ATTRIBUTES:
            return None
        valid_updates: list[tuple[str, str, float]] = []
        for update in updates[:5]:
            if not isinstance(update, dict):
                return None
            attribute = update.get("attribute")
            value = update.get("value")
            confidence = update.get("confidence")
            if attribute not in ALLOWED_ATTRIBUTES or not isinstance(value, str):
                return None
            if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                return None
            valid_updates.append((attribute, value[:200], min(float(confidence), 0.75)))
        valid_order: list[str] = []
        seen: set[str] = set()
        for value in ordering:
            identifier = str(value)
            if identifier in allowed_ids and identifier not in seen:
                valid_order.append(identifier)
                seen.add(identifier)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        if not isinstance(prompt_tokens, int) or prompt_tokens < 0:
            prompt_tokens = 0
        if not isinstance(completion_tokens, int) or completion_tokens < 0:
            completion_tokens = 0
        return Enhancement(
            query_rewrite=query_rewrite.strip(),
            slot_updates=tuple(valid_updates),
            candidate_order=tuple(valid_order),
            next_attribute=next_attribute,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
