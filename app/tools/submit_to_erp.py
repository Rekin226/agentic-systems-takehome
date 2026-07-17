"""
submit_to_erp: the single irreversible, high-risk tool.

requires_approval = True. This flag is the entire approval boundary at the tool
layer: the harness refuses to invoke any tool whose requires_approval is True
unless the run has reached an approved state. Even if a compromised planner (or
a prompt injection) explicitly asks for submit_to_erp, the harness blocks it;
the guarantee lives in code, not in a prompt.
"""

from __future__ import annotations

from app.schemas import SubmitToErpInput, SubmitToErpOutput
from app.tools.base import Tool


class SubmitToErpTool(Tool):
    name = "submit_to_erp"
    input_model = SubmitToErpInput
    requires_approval = True  # <-- the boundary marker

    def run(self, payload: SubmitToErpInput) -> SubmitToErpOutput:
        # Mock ERP submission. In reality this posts to an external system.
        reference = f"ERP-{payload.run_id}"
        return SubmitToErpOutput(erp_reference=reference, submitted=True)
