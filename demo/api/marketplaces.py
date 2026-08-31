from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True, slots=True)
class Marketplace:
    code: str
    label: str
    domain: str

    def search_url(self, parent_asin: str) -> str:
        return f"https://{self.domain}/s?k={quote_plus(parent_asin)}"


_MARKETPLACES = (
    Marketplace("SG", "Singapore", "www.amazon.sg"),
    Marketplace("US", "United States", "www.amazon.com"),
    Marketplace("AU", "Australia", "www.amazon.com.au"),
    Marketplace("UK", "United Kingdom", "www.amazon.co.uk"),
    Marketplace("JP", "Japan", "www.amazon.co.jp"),
    Marketplace("CA", "Canada", "www.amazon.ca"),
    Marketplace("DE", "Germany", "www.amazon.de"),
    Marketplace("FR", "France", "www.amazon.fr"),
    Marketplace("IT", "Italy", "www.amazon.it"),
    Marketplace("ES", "Spain", "www.amazon.es"),
    Marketplace("IN", "India", "www.amazon.in"),
    Marketplace("NL", "Netherlands", "www.amazon.nl"),
    Marketplace("BR", "Brazil", "www.amazon.com.br"),
    Marketplace("MX", "Mexico", "www.amazon.com.mx"),
    Marketplace("BE", "Belgium", "www.amazon.com.be"),
    Marketplace("IE", "Ireland", "www.amazon.ie"),
    Marketplace("PL", "Poland", "www.amazon.pl"),
    Marketplace("SE", "Sweden", "www.amazon.se"),
    Marketplace("AE", "United Arab Emirates", "www.amazon.ae"),
    Marketplace("SA", "Saudi Arabia", "www.amazon.sa"),
    Marketplace("TR", "Turkey", "www.amazon.com.tr"),
    Marketplace("EG", "Egypt", "www.amazon.eg"),
)

MARKETPLACES = {item.code: item for item in _MARKETPLACES}


def marketplace_payload() -> list[dict[str, str]]:
    return [
        {"code": item.code, "label": item.label, "domain": item.domain}
        for item in _MARKETPLACES
    ]
