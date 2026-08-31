from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, Sequence


class CatalogEnricher(Protocol):
    """Future live-catalog seam; implementations must preserve input ASIN order."""

    def enrich(self, parent_asins: Sequence[str], marketplace: str) -> dict[str, dict]: ...


@dataclass(frozen=True, slots=True)
class CreatorsApiConfiguration:
    credential_id: str
    credential_secret: str
    credential_version: str
    partner_tag: str

    @classmethod
    def from_environment(cls, marketplace: str) -> "CreatorsApiConfiguration | None":
        values = {
            "credential_id": os.environ.get("AMAZON_CREATORS_CREDENTIAL_ID", "").strip(),
            "credential_secret": os.environ.get("AMAZON_CREATORS_CREDENTIAL_SECRET", "").strip(),
            "credential_version": os.environ.get("AMAZON_CREATORS_CREDENTIAL_VERSION", "").strip(),
            "partner_tag": os.environ.get(f"AMAZON_CREATORS_PARTNER_TAG_{marketplace}", "").strip(),
        }
        if not all(values.values()):
            return None
        return cls(**values)


class LocalCatalogEnricher:
    """No-network default used until Creators API credentials are available."""

    def enrich(self, parent_asins: Sequence[str], marketplace: str) -> dict[str, dict]:
        del marketplace
        return {parent_asin: {} for parent_asin in parent_asins}


class CreatorsApiEnricher:
    """Credential gate for a later live adapter.

    The competition experience intentionally does not issue live Amazon requests
    until an accepted Associates account, marketplace Partner Tag, and test
    credentials are available. Keeping the seam explicit prevents snapshot data
    from being mislabeled as live inventory.
    """

    def __init__(self, marketplace: str) -> None:
        self.marketplace = marketplace
        self.configuration = CreatorsApiConfiguration.from_environment(marketplace)

    @property
    def available(self) -> bool:
        return self.configuration is not None

    def enrich(self, parent_asins: Sequence[str], marketplace: str) -> dict[str, dict]:
        if marketplace != self.marketplace or self.configuration is None:
            return {parent_asin: {} for parent_asin in parent_asins}
        # Deliberately fail closed until a credentialed contract test is possible.
        return {parent_asin: {} for parent_asin in parent_asins}
