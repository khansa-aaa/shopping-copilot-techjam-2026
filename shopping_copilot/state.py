from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from .catalog import COLORS, MATERIALS, terms


ALLOWED_ATTRIBUTES = {
    "category", "material", "color", "size", "style", "brand", "budget",
    "feature", "use_case", "other",
}
OVERRIDE_RE = re.compile(
    r"\b(actually|instead|changed? my mind|ignore (?:my )?(?:earlier|previous)|new priority)\b",
    re.I,
)
NO_PREFERENCE_RE = re.compile(
    r"(?:don['’]t|do not) have (?:an? |any )?(?:additional )?preference for\s+([a-z_ ]+)",
    re.I,
)
BUDGET_RE = re.compile(
    r"(?:budget(?: around| of)?|under|below|less than|up to|max(?:imum)?)\s*\$?\s*([0-9]+(?:\.[0-9]+)?)",
    re.I,
)


@dataclass(slots=True)
class Evidence:
    value: str
    confidence: float
    hard: bool
    turn: int
    generation: int
    source: str


@dataclass(frozen=True, slots=True)
class EnhancementStatus:
    """JSON-safe status for the optional enhancement on one response turn."""

    turn: int = 0
    outcome: str = "not_started"
    enabled: bool = False
    attempted: bool = False
    applied: bool = False
    model: str = "gpt-5.6-luna"
    reasoning_effort: str = "none"
    calls_used: int = 0
    max_calls: int = 2
    timeout_seconds: float = 2.5
    rank_blend: float = 1.0
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def as_dict(self) -> dict:
        return {
            "turn": self.turn,
            "outcome": self.outcome,
            "enabled": self.enabled,
            "attempted": self.attempted,
            "applied": self.applied,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "calls_used": self.calls_used,
            "max_calls": self.max_calls,
            "timeout_seconds": self.timeout_seconds,
            "rank_blend": self.rank_blend,
            "latency_ms": round(self.latency_ms, 3),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


@dataclass(slots=True)
class SessionState:
    session_id: str
    user_profile: dict
    route_probabilities: dict[str, float] = field(default_factory=lambda: {
        "buying": 0.25,
        "browsing": 0.50,
        "focused": 0.20,
        "override": 0.05,
    })
    slots: dict[str, list[Evidence]] = field(default_factory=dict)
    no_preferences: set[str] = field(default_factory=set)
    rejected: set[str] = field(default_factory=set)
    last_recommendations: tuple[str, ...] = ()
    turn: int = 0
    intent_generation: int = 0
    confidence: float = 0.0
    hardness: float = 0.0
    openai_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    enhancement_status: EnhancementStatus = field(default_factory=EnhancementStatus)

    @property
    def profile_priors(self) -> tuple[str, ...]:
        tags = self.user_profile.get("preference_tags")
        if not isinstance(tags, list):
            return ()
        return tuple(str(value).strip().lower() for value in tags if str(value).strip())

    def active_evidence(self, attribute: str | None = None) -> list[Evidence]:
        values: list[Evidence] = []
        groups = self.slots.items() if attribute is None else ((attribute, self.slots.get(attribute, [])),)
        for _, evidence in groups:
            values.extend(
                item for item in evidence
                if item.generation == self.intent_generation or item.source == "category"
            )
        return values

    def query_text(self, include_profile: bool = True) -> str:
        evidence = sorted(self.active_evidence(), key=lambda item: (not item.hard, -item.confidence, item.turn))
        chunks = [item.value for item in evidence if item.confidence >= 0.30]
        if include_profile:
            chunks.extend(self.profile_priors)
        return " ".join(dict.fromkeys(chunks))

    def add_evidence(
        self,
        attribute: str,
        value: str,
        *,
        confidence: float,
        hard: bool,
        source: str,
    ) -> None:
        cleaned = re.sub(r"\s+", " ", value).strip(" .;,\t\n")[:500]
        if not cleaned:
            return
        bucket = self.slots.setdefault(attribute, [])
        lowered = cleaned.casefold()
        for existing in bucket:
            if existing.value.casefold() == lowered and (
                existing.generation == self.intent_generation or source == "category"
            ):
                existing.confidence = max(existing.confidence, confidence)
                existing.hard = existing.hard or hard
                existing.turn = self.turn
                return
        bucket.append(Evidence(
            value=cleaned,
            confidence=max(0.0, min(1.0, confidence)),
            hard=hard,
            turn=self.turn,
            generation=self.intent_generation,
            source=source,
        ))

    def start_turn(self, user_message: str, turn: int) -> bool:
        if not 1 <= turn <= 10:
            raise ValueError("turn must be between 1 and 10")
        if turn < self.turn:
            raise ValueError("turn cannot go backwards")
        if turn > self.turn and self.last_recommendations:
            self.rejected.update(self.last_recommendations)
        for evidence in self.active_evidence():
            if not evidence.hard and evidence.source != "category":
                evidence.confidence *= 0.84

        self.turn = turn
        is_override = bool(OVERRIDE_RE.search(user_message))
        if is_override:
            self.intent_generation += 1
            self.rejected.clear()
            self.no_preferences.clear()
            self.route_probabilities = {
                "buying": 0.10,
                "browsing": 0.05,
                "focused": 0.15,
                "override": 0.70,
            }

        self._parse_message(user_message, is_override=is_override)
        active = self.active_evidence()
        hard = [item for item in active if item.hard and item.source != "category"]
        specific = [item for item in active if item.source != "category"]
        self.hardness = min(1.0, 0.45 * len(hard) + 0.12 * max(0, len(specific) - len(hard)))
        self.confidence = min(1.0, sum(item.confidence for item in specific) / 2.5)
        if not is_override:
            if hard:
                self.route_probabilities = {"buying": 0.48, "browsing": 0.05, "focused": 0.42, "override": 0.05}
            elif specific:
                self.route_probabilities = {"buying": 0.20, "browsing": 0.20, "focused": 0.55, "override": 0.05}
            else:
                self.route_probabilities = {"buying": 0.08, "browsing": 0.77, "focused": 0.10, "override": 0.05}
        return is_override

    def _parse_message(self, message: str, *, is_override: bool) -> None:
        no_preference = NO_PREFERENCE_RE.search(message)
        if no_preference:
            raw_attribute = no_preference.group(1).strip().lower().replace(" ", "_")
            attribute = raw_attribute if raw_attribute in ALLOWED_ATTRIBUTES else "other"
            self.no_preferences.add(attribute)
            return

        category_match = re.search(
            r"(?:i['’]m|i am) looking for\s+(.+?)(?:[.]|,\s*(?:but|and)|$)",
            message,
            re.I,
        )
        if category_match:
            category = category_match.group(1).strip()
            if category and category.casefold() not in {"something", "a product", "product"}:
                self.add_evidence("category", category, confidence=1.0, hard=True, source="category")

        values: list[tuple[str, bool, str]] = []
        key_requirement = re.search(r"key requirement is:\s*(.+)$", message, re.I)
        matters = re.search(r"what matters is:\s*(.+)$", message, re.I)
        override_value = re.search(r"what i need is:\s*(.+)$", message, re.I)
        if override_value:
            values.extend((value, True, "override") for value in _split_values(override_value.group(1)))
        elif key_requirement:
            values.extend((value, True, "explicit_hard") for value in _split_values(key_requirement.group(1)))
        elif matters:
            values.extend((value, self.turn <= 3, "clarification") for value in _split_values(matters.group(1)))
        elif is_override:
            tail = re.split(r"\b(?:instead|actually)\b", message, flags=re.I)[-1]
            values.extend((tail, True, "override") for _ in [0] if tail.strip())
        else:
            # Non-simulator phrasing still contributes as soft intent.
            cleaned = re.sub(r"(?:i['’]m|i am) looking for\s+[^.,]+[.,]?", "", message, flags=re.I).strip()
            if len(terms(cleaned)) >= 2 and "not quite right" not in cleaned.lower():
                values.append((cleaned, False, "message"))

        for value, hard, source in values:
            attribute = classify_attribute(value)
            self.add_evidence(
                attribute,
                value,
                confidence=0.98 if hard else 0.72,
                hard=hard,
                source=source,
            )

    def distilled(self) -> dict:
        return {
            "turn": self.turn,
            "intent_generation": self.intent_generation,
            "route_probabilities": self.route_probabilities,
            "slots": {
                name: [
                    {"value": item.value, "confidence": round(item.confidence, 3), "hard": item.hard}
                    for item in values if item in self.active_evidence(name)
                ]
                for name, values in self.slots.items()
            },
            "no_preferences": sorted(self.no_preferences),
            "profile_priors": list(self.profile_priors),
        }


def _split_values(value: str) -> list[str]:
    return [item.strip(" .;,\t\n") for item in value.split(";") if item.strip(" .;,\t\n")]


def classify_attribute(value: str) -> str:
    lowered = value.lower()
    if BUDGET_RE.search(lowered) or re.search(r"(?:\$|<=)\s*\d", lowered):
        return "budget"
    if any(re.search(rf"\b{re.escape(material)}\b", lowered) for material in MATERIALS):
        return "material"
    if any(re.search(rf"\b{re.escape(color)}\b", lowered) for color in COLORS):
        return "color"
    if any(word in lowered for word in ("size", "sizing", "width", "wide", "narrow", "inch")):
        return "size"
    if any(word in lowered for word in ("brand", "manufacturer", "made by")):
        return "brand"
    if any(word in lowered for word in ("department", "style", "fit", "sleeve", "neck", "closure")):
        return "style"
    if any(word in lowered for word in ("hiking", "running", "gym", "winter", "outdoor", "work", "wedding", "travel")):
        return "use_case"
    return "feature"


def budget_ceiling(evidence: Evidence) -> float | None:
    match = BUDGET_RE.search(evidence.value)
    return float(match.group(1)) if match else None


def normalize_profile(profile: Mapping[str, object]) -> dict:
    result = dict(profile)
    tags = result.get("preference_tags")
    result["preference_tags"] = [str(value) for value in tags] if isinstance(tags, list) else []
    return result
