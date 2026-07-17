"""
schemas.py: the contracts at every boundary.

In this system the schemas define the design; they are not incidental detail.
Every arrow in the request lifecycle crosses a Pydantic model:

    HTTP in ──► RunRequest
    Planner out ──► ParsedIntent        (untrusted, validated, never blindly trusted)
    Tool in/out ──► *Input / *Output    (validated before and after each tool)
    Final out ──► AgentRunResponse      (must pass validation before we return)

Guardrails A (final output validation) and B (tool input validation) from the
spec are enforced simply by *using* these models at the boundaries.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums, the closed vocabularies. Using enums (not free strings) means an
# invalid action/status can't silently leak into a downstream system.
# ---------------------------------------------------------------------------


class Action(str, Enum):
    """The four terminal decisions the agent can reach."""

    CREATE_DRAFT_PO = "CREATE_DRAFT_PO"
    NEED_HUMAN_APPROVAL = "NEED_HUMAN_APPROVAL"
    REJECT = "REJECT"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RunStatus(str, Enum):
    """Lifecycle state of a single Agent Run."""

    COMPLETED = "COMPLETED"            # draft PO created, nothing pending
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REJECTED = "REJECTED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"               # refused by the approval boundary


# ---------------------------------------------------------------------------
# API boundary
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """POST /agent/run body. Validated at the door, guardrail B for HTTP input."""

    user_id: str = Field(..., min_length=1)
    department: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Planner output, the "understanding" layer.
#
# Important: this is what the planner (rules today, an LLM tomorrow) infers
# the user wants. It is an untrusted proposal. The harness validates it against
# this schema and the ApprovalGate can overrule it. Authority lives downstream,
# never here.
# ---------------------------------------------------------------------------


class ParsedIntent(BaseModel):
    raw_message: str
    item_query: Optional[str] = None       # e.g. "figma enterprise" (may be unresolved)
    quantity: Optional[int] = Field(default=None, ge=1)
    department: str
    budget_cap: Optional[float] = None     # user-stated ceiling, if any ("under 3000")
    injection_detected: bool = False       # planner flagged a bypass/override attempt
    missing_fields: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class CatalogItem(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    unit_price: float
    category: str


class DraftPO(BaseModel):
    item: str
    quantity: int
    unit_price: float
    estimated_total: float
    department: str


# ---------------------------------------------------------------------------
# Tool I/O contracts, one Input + one Output model per tool.
# The harness validates input before calling and trusts output only after it
# parses back into the Output model.
# ---------------------------------------------------------------------------


class LookupCatalogInput(BaseModel):
    query: str = Field(..., min_length=1)


class LookupCatalogOutput(BaseModel):
    found: bool
    item: Optional[CatalogItem] = None


class CheckPolicyInput(BaseModel):
    category: str
    estimated_total: float = Field(..., ge=0)
    department: str
    injection_detected: bool = False


class CheckPolicyOutput(BaseModel):
    risk_level: RiskLevel
    requires_human_approval: bool
    triggered_rules: list[str] = Field(default_factory=list)  # e.g. ["policy_002"]
    reason: str


class CreateDraftPOInput(BaseModel):
    item: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1)
    unit_price: float = Field(..., ge=0)
    estimated_total: float = Field(..., ge=0)
    department: str = Field(..., min_length=1)


class CreateDraftPOOutput(BaseModel):
    draft_po: DraftPO


class SubmitToErpInput(BaseModel):
    run_id: str
    draft_po: DraftPO


class SubmitToErpOutput(BaseModel):
    erp_reference: str
    submitted: bool


# ---------------------------------------------------------------------------
# Trace + final response
# ---------------------------------------------------------------------------


class ToolCall(BaseModel):
    """One entry in the execution trace. Makes the run auditable."""

    tool: str
    status: ToolStatus
    input: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    error: Optional[str] = None


class Decision(BaseModel):
    action: Action
    risk_level: RiskLevel
    requires_human_approval: bool
    reason: str
    triggered_rules: list[str] = Field(default_factory=list)


class AgentRunResponse(BaseModel):
    """The final structured output. Guardrail A: this must parse before return."""

    run_id: str
    status: RunStatus
    decision: Decision
    draft_po: Optional[DraftPO] = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
