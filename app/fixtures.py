"""
fixtures.py: load the mock enterprise data once, at startup.

This is the "trusted world": catalog, policies, budgets. It is the source of
truth the ApprovalGate enforces against. Note the asymmetry that defines the
whole system's security:

    fixtures  = trusted   (loaded from disk, controlled by us)
    message   = untrusted (typed by a user, may be adversarial)

A user's words can never edit this data, they can only be parsed into a
proposal that is then checked *against* it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.schemas import CatalogItem

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load(name: str):
    with open(_FIXTURES_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


class Fixtures:
    """In-memory view of catalog / policies / budgets."""

    def __init__(self) -> None:
        self.catalog: list[CatalogItem] = [CatalogItem(**row) for row in _load("catalog.json")]
        self.policies: dict = _load("policies.json")
        self.budgets: dict = _load("budgets.json")

    # -- catalog -----------------------------------------------------------
    def find_item(self, query: str) -> Optional[CatalogItem]:
        """Resolve a free-text query to a catalog item via name/alias match."""
        if not query:
            return None
        q = query.strip().lower()
        for item in self.catalog:
            haystack = [item.name.lower(), *(a.lower() for a in item.aliases)]
            if any(q == h or q in h or h in q for h in haystack):
                return item
        return None

    # -- policies ----------------------------------------------------------
    @property
    def approval_threshold(self) -> float:
        return float(self.policies["approval_threshold_usd"])

    @property
    def restricted_categories(self) -> list[str]:
        return list(self.policies.get("restricted_categories", []))

    # -- budgets -----------------------------------------------------------
    def remaining_budget(self, department: str) -> Optional[float]:
        dept = self.budgets.get(department)
        return float(dept["remaining_budget_usd"]) if dept else None


# Single shared instance, loaded once, reused across runs.
fixtures = Fixtures()
