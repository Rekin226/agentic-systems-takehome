"""lookup_catalog: resolve a free-text item query to a catalog entry."""

from __future__ import annotations

from app.fixtures import fixtures
from app.schemas import LookupCatalogInput, LookupCatalogOutput
from app.tools.base import Tool


class LookupCatalogTool(Tool):
    name = "lookup_catalog"
    input_model = LookupCatalogInput
    requires_approval = False

    def run(self, payload: LookupCatalogInput) -> LookupCatalogOutput:
        item = fixtures.find_item(payload.query)
        return LookupCatalogOutput(found=item is not None, item=item)
