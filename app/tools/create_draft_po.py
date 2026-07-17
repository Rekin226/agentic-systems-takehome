"""
create_draft_po: build a draft purchase order.

Low-risk: a draft is not an order. It creates no financial commitment, so it
does not require approval. Submitting the draft to the ERP is the irreversible
step, and that lives in submit_to_erp (requires_approval=True).
"""

from __future__ import annotations

from app.schemas import CreateDraftPOInput, CreateDraftPOOutput, DraftPO
from app.tools.base import Tool


class CreateDraftPOTool(Tool):
    name = "create_draft_po"
    input_model = CreateDraftPOInput
    requires_approval = False

    def run(self, payload: CreateDraftPOInput) -> CreateDraftPOOutput:
        draft = DraftPO(
            item=payload.item,
            quantity=payload.quantity,
            unit_price=payload.unit_price,
            estimated_total=payload.estimated_total,
            department=payload.department,
        )
        return CreateDraftPOOutput(draft_po=draft)
