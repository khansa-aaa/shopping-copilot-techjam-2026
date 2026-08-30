from __future__ import annotations

import json
import math
import re
import sqlite3
import zlib
from array import array
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
PRICE_RE = re.compile(r"(?:US\$|USD|\$)?\s*([0-9]+(?:\.[0-9]{1,2})?)", re.I)
MATERIALS = (
    "cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk",
    "rayon", "linen", "denim", "suede", "fleece", "canvas", "rubber",
    "stainless steel", "gold", "silver", "fabric",
)
COLORS = (
    "black", "white", "blue", "red", "pink", "green", "brown", "gray",
    "grey", "purple", "yellow", "orange", "beige", "navy", "gold", "silver",
)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "do", "for",
    "from", "have", "i", "in", "is", "it", "me", "my", "of", "on", "or",
    "please", "some", "that", "the", "this", "to", "want", "what", "with",
    "would", "you", "looking", "still", "here", "those", "not", "quite",
    "right", "yet", "about", "one", "specific", "attribute", "matters",
}
SYNONYMS: Mapping[str, tuple[str, ...]] = {
    "shoe": ("shoes", "sneaker", "footwear"),
    "shoes": ("shoe", "sneaker", "footwear"),
    "shirt": ("shirts", "tee", "tshirt", "top"),
    "shirts": ("shirt", "tee", "tshirt", "top"),
    "pants": ("trousers", "slacks"),
    "jacket": ("coat", "outerwear"),
    "dress": ("gown",),
    "bag": ("handbag", "purse", "backpack"),
    "watch": ("timepiece",),
    "running": ("athletic", "sport", "jogging"),
    "winter": ("warm", "insulated", "cold"),
    "women": ("womens", "female"),
    "men": ("mens", "male"),
}


def flatten_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten_text(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(flatten_text(item) for item in value)
    return str(value)


def terms(text: str, *, limit: int | None = None) -> list[str]:
    result = [
        token.lower() for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.lower() not in STOPWORDS
    ]
    return result if limit is None else result[:limit]


def normalize_price(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    match = PRICE_RE.search(str(value).replace(",", ""))
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _tuple_text(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item) for item in value if item not in (None, ""))
    if value in (None, ""):
        return ()
    return (str(value),)


@dataclass(frozen=True, slots=True)
class Product:
    parent_asin: str
    title: str
    features: tuple[str, ...]
    description: tuple[str, ...]
    price: float | None
    categories: tuple[str, ...]
    details: tuple[tuple[str, str], ...]
    average_rating: float
    rating_number: int
    store: str
    search_text: str

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> "Product":
        identifier = str(raw.get("parent_asin") or "").strip()
        if not identifier:
            raise ValueError("catalog row has no parent_asin")
        details_raw = raw.get("details")
        details = tuple(
            (str(key), flatten_text(value))
            for key, value in (details_raw.items() if isinstance(details_raw, dict) else ())
            if value not in (None, "", [])
        )
        features = _tuple_text(raw.get("features"))
        description = _tuple_text(raw.get("description"))
        categories = _tuple_text(raw.get("categories"))
        title = str(raw.get("title") or "")
        store = str(raw.get("store") or "")
        chunks = (
            title,
            " ".join(categories),
            " ".join(features),
            " ".join(f"{key} {value}" for key, value in details),
            store,
            " ".join(description),
        )
        try:
            rating = float(raw.get("average_rating") or 0.0)
        except (TypeError, ValueError):
            rating = 0.0
        try:
            rating_number = max(0, int(raw.get("rating_number") or 0))
        except (TypeError, ValueError):
            rating_number = 0
        return cls(
            parent_asin=identifier,
            title=title,
            features=features,
            description=description,
            price=normalize_price(raw.get("price")),
            categories=categories,
            details=details,
            average_rating=rating if math.isfinite(rating) else 0.0,
            rating_number=rating_number,
            store=store,
            search_text=" ".join(chunks).lower(),
        )


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    index: int
    score: float
    routes: tuple[str, ...] = ()


class CatalogIndex:
    """In-memory facets, weighted FTS5, and a 256D catalog-derived hash index."""

    dimensions = 256

    def __init__(self, catalog_path: str | Path) -> None:
        self.path = Path(catalog_path)
        if not self.path.is_file():
            raise FileNotFoundError(f"catalog not found: {self.path}")
        self.products = self._load_products()
        self.ids = tuple(product.parent_asin for product in self.products)
        self.id_to_index = {value: index for index, value in enumerate(self.ids)}
        if len(self.id_to_index) != len(self.ids):
            raise ValueError("catalog contains duplicate parent_asin values")
        self.facets: dict[str, dict[str, set[int]]] = {
            name: defaultdict(set) for name in ("material", "color", "brand", "category")
        }
        self._document_frequency: Counter[str] = Counter()
        self._build_facets_and_df()
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self._build_fts()
        self._dense = self._build_dense_index()

    def _load_products(self) -> list[Product]:
        products: list[Product] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    products.append(Product.from_json(json.loads(line)))
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise ValueError(f"invalid catalog row {line_number}: {exc}") from exc
        if not products:
            raise ValueError("catalog is empty")
        return products

    def _build_facets_and_df(self) -> None:
        for index, product in enumerate(self.products):
            unique = set(terms(product.search_text))
            self._document_frequency.update(unique)
            lowered = product.search_text
            for material in MATERIALS:
                if re.search(rf"\b{re.escape(material)}\b", lowered):
                    self.facets["material"][material].add(index)
            for color in COLORS:
                if re.search(rf"\b{re.escape(color)}\b", lowered):
                    self.facets["color"][color].add(index)
            if product.store:
                self.facets["brand"][product.store.casefold()].add(index)
            for category in product.categories:
                lowered_category = category.casefold().strip()
                if lowered_category:
                    self.facets["category"][lowered_category].add(index)
                    for token in terms(lowered_category):
                        self.facets["category"][token].add(index)

    def _build_fts(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            "CREATE VIRTUAL TABLE products USING fts5("
            "parent_asin UNINDEXED, title, categories, features, details, store, description, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        batch: list[tuple[str, str, str, str, str, str, str]] = []
        for product in self.products:
            batch.append((
                product.parent_asin,
                product.title,
                " ".join(product.categories),
                " ".join(product.features),
                " ".join(f"{key} {value}" for key, value in product.details),
                product.store,
                " ".join(product.description),
            ))
            if len(batch) >= 1000:
                cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                batch.clear()
        if batch:
            cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
        self.connection.commit()

    @staticmethod
    def _hash_term(token: str) -> tuple[int, float]:
        digest = zlib.crc32(token.encode("utf-8")) & 0xFFFFFFFF
        return digest & 255, -1.0 if digest & 256 else 1.0

    def _idf(self, token: str) -> float:
        count = self._document_frequency.get(token, 0)
        return math.log1p((len(self.products) + 1) / (count + 1))

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        counts = Counter(terms(text, limit=220))
        expanded = Counter(counts)
        for token, count in tuple(counts.items()):
            for synonym in SYNONYMS.get(token, ()):
                expanded[synonym] += 0.45 * count
        for token, count in expanded.items():
            dimension, sign = self._hash_term(token)
            vector[dimension] += sign * min(float(count), 3.0) * self._idf(token)
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    def _build_dense_index(self) -> array:
        dense = array("f")
        for product in self.products:
            dense.extend(self._vector(product.search_text))
        return dense

    def fts(self, query: str, *, limit: int = 500, conjunctive: bool = False) -> list[int]:
        unique = list(dict.fromkeys(terms(query, limit=50)))
        if not unique:
            return []
        joiner = " AND " if conjunctive and len(unique) <= 14 else " OR "
        expression = joiner.join(f'"{token}"' for token in unique)
        try:
            rows = self.connection.execute(
                "SELECT rowid FROM products WHERE products MATCH ? "
                "ORDER BY bm25(products, 0.0, 7.0, 4.5, 3.0, 2.5, 2.0, 1.0) LIMIT ?",
                (expression, int(limit)),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [int(row[0]) - 1 for row in rows]

    def facet_candidates(self, attribute: str, value: str) -> set[int] | None:
        mapping = self.facets.get(attribute)
        if not mapping:
            return None
        lowered = value.casefold()
        matched: list[set[int]] = []
        for facet_value, indices in mapping.items():
            if facet_value in lowered or lowered in facet_value:
                matched.append(indices)
        if not matched:
            return None
        result = set(matched[0])
        for indices in matched[1:]:
            result.update(indices)
        return result

    def dense_scores(self, query: str, candidates: Iterable[int]) -> dict[int, float]:
        vector = self._vector(query)
        nonzero = [(i, value) for i, value in enumerate(vector) if value]
        scores: dict[int, float] = {}
        for index in candidates:
            offset = index * self.dimensions
            scores[index] = sum(self._dense[offset + dim] * value for dim, value in nonzero)
        return scores

    @lru_cache(maxsize=4096)
    def token_set(self, index: int) -> frozenset[str]:
        return frozenset(terms(self.products[index].search_text))

    def distribution(self, candidates: Sequence[int], attribute: str) -> Counter[str]:
        counts: Counter[str] = Counter()
        if attribute == "brand":
            counts.update(
                self.products[index].store.casefold()
                for index in candidates if self.products[index].store
            )
            return counts
        if attribute == "category":
            counts.update(
                self.products[index].categories[-1].casefold()
                for index in candidates if self.products[index].categories
            )
            return counts
        values = MATERIALS if attribute == "material" else COLORS if attribute == "color" else ()
        for index in candidates:
            text = self.products[index].search_text
            for value in values:
                if value in text:
                    counts[value] += 1
        return counts

    def close(self) -> None:
        self.connection.close()
