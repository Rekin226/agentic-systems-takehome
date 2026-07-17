"""
harness.py: the Agent Runtime, the layer this exercise primarily evaluates (Section 2).

It orchestrates one Agent Run and owns all control. Responsibilities (mapped to
the spec's checklist):

  1. init run state ................ run() creates a RunState
  2. call planner .................. self.planner.plan(...)
  3. call tools by planner signal .. self._invoke_tool(...)
  4. validate tool input ........... _invoke_tool -> tool.validate_input  (guardrail B)
  5. intercept unauthorized calls .. _invoke_tool approval check          (guardrail C)
  6. record tool call trace ........ state.record(ToolCall(...))
  7. produce structured output ..... _build_response(...)
  8. schema-validate the output .... AgentRunResponse.model_validate(...) (guardrail A)

Every tool call in the system funnels through _invoke_tool. That is deliberate:
there is exactly one place where input is validated, authorization is enforced,
and the trace is written. No tool can be reached any other way.
"""

from __future__ import annotations

import uuid
from typing import Optional

from app.fixtures import fixtures
from app.gate import ApprovalGate
from app.planner import Planner, make_planner
from app.schemas import (
    Action,
    AgentRunResponse,
    DraftPO,
    RunRequest,
    RunStatus,
    ToolCall,
    ToolStatus,
)
from app.state import RunState, RunStore, run_store
from app.tools.registry import ToolRegistry, default_registry


class ApprovalRequiredError(Exception):
    """Raised when a high-risk tool is invoked before the run is approved."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Tool '{tool_name}' requires approval before it may run.")
        self.tool_name = tool_name


_STATUS_FOR_ACTION = {
    Action.CREATE_DRAFT_PO: RunStatus.COMPLETED,
    Action.NEED_HUMAN_APPROVAL: RunStatus.AWAITING_APPROVAL,
    Action.REJECT: RunStatus.REJECTED,
    Action.ASK_CLARIFICATION: RunStatus.NEEDS_CLARIFICATION,
}


class AgentHarness:
    def __init__(
        self,
        planner: Optional[Planner] = None,
        gate: Optional[ApprovalGate] = None,
        registry: Optional[ToolRegistry] = None,
        store: Optional[RunStore] = None,
    ) -> None:
        self.planner = planner or make_planner()  # AGENT_PLANNER selects rule vs llm
        self.gate = gate or ApprovalGate()
        self.registry = registry or default_registry()
        self.store = store or run_store

    # ------------------------------------------------------------------ #
    # The single, controlled path to every tool.
    # ------------------------------------------------------------------ #
    def _invoke_tool(self, state: RunState, name: str, raw_input: dict):
        tool = self.registry.get(name)

        # Guardrail C, approval boundary at the tool layer. A high-risk tool
        # may only run once the run has been explicitly approved. This holds
        # even if a planner/LLM/injection explicitly demanded the tool.
        if tool.requires_approval and not state.approved:
            state.record(
                ToolCall(
                    tool=name,
                    status=ToolStatus.BLOCKED,
                    input=raw_input,
                    error="Approval required before this tool may run.",
                )
            )
            raise ApprovalRequiredError(name)

        # Guardrail B, never trust caller-supplied params.
        try:
            payload = tool.validate_input(raw_input)
        except Exception as exc:  # pydantic ValidationError etc.
            state.record(
                ToolCall(tool=name, status=ToolStatus.ERROR, input=raw_input, error=str(exc))
            )
            raise

        output = tool.run(payload)
        state.record(
            ToolCall(
                tool=name,
                status=ToolStatus.SUCCESS,
                input=raw_input,
                output=output.model_dump(),
            )
        )
        return output

    # ------------------------------------------------------------------ #
    # Run one agent turn.
    # ------------------------------------------------------------------ #
    def run(self, request: RunRequest) -> AgentRunResponse:
        state = RunState(
            run_id=f"run_{uuid.uuid4().hex[:8]}",
            user_id=request.user_id,
            department=request.department,
            message=request.message,
        )

        # 2. Understand the (untrusted) message.
        intent = self.planner.plan(request.message, request.department)

        # 3-6. Gather signals through validated, traced tool calls.
        item = None
        estimated_total = None
        policy = None
        remaining_budget = fixtures.remaining_budget(request.department)

        # Resolve the item whenever we have a query, even if quantity is
        # missing, so the clarification can be precise ("found X, how many?")
        # instead of wrongly claiming the item itself is unknown.
        if intent.item_query:
            lookup_out = self._invoke_tool(state, "lookup_catalog", {"query": intent.item_query})
            item = lookup_out.item
            if item is not None and intent.quantity:
                estimated_total = item.unit_price * intent.quantity
                policy = self._invoke_tool(
                    state,
                    "check_policy",
                    {
                        "category": item.category,
                        "estimated_total": estimated_total,
                        "department": request.department,
                        "injection_detected": intent.injection_detected,
                    },
                )
                # Prepare a PO candidate now so an approval flow can act on it later.
                state.candidate_po = DraftPO(
                    item=item.name,
                    quantity=intent.quantity,
                    unit_price=item.unit_price,
                    estimated_total=estimated_total,
                    department=request.department,
                )

        # 7. The gate, the sole authority, selects the action.
        decision = self.gate.decide(intent, item, estimated_total, policy, remaining_budget)
        state.decision = decision

        # 8. Act only if the decision permits it (low-risk draft creation).
        if decision.action == Action.CREATE_DRAFT_PO and state.candidate_po is not None:
            draft_out = self._invoke_tool(
                state,
                "create_draft_po",
                state.candidate_po.model_dump(),
            )
            state.draft_po = draft_out.draft_po

        state.status = _STATUS_FOR_ACTION[decision.action]
        self.store.save(state)

        return self._build_response(state)

    # ------------------------------------------------------------------ #
    # Optional approval flow: POST /agent/runs/:id/approve
    # ------------------------------------------------------------------ #
    def approve(self, run_id: str) -> AgentRunResponse:
        state = self.store.get(run_id)
        if state is None:
            raise KeyError(run_id)
        if state.decision is None or state.decision.action != Action.NEED_HUMAN_APPROVAL:
            # Only runs actually awaiting approval can be approved.
            raise ValueError(f"Run {run_id} is not awaiting approval.")

        # A human has approved. Now high-risk tools become reachable.
        state.approved = True

        if state.candidate_po is not None:
            # Materialize the draft (if it wasn't created) and submit to ERP.
            if state.draft_po is None:
                draft_out = self._invoke_tool(
                    state, "create_draft_po", state.candidate_po.model_dump()
                )
                state.draft_po = draft_out.draft_po
            self._invoke_tool(
                state,
                "submit_to_erp",
                {"run_id": run_id, "draft_po": state.draft_po.model_dump()},
            )

        state.status = RunStatus.COMPLETED
        self.store.save(state)
        return self._build_response(state)

    # ------------------------------------------------------------------ #
    # Guardrail A, assemble and schema-validate the final output.
    # ------------------------------------------------------------------ #
    def _build_response(self, state: RunState) -> AgentRunResponse:
        payload = {
            "run_id": state.run_id,
            "status": state.status,
            "decision": state.decision,
            "draft_po": state.draft_po,
            "tool_calls": state.trace,
        }
        # model_validate re-parses the whole thing: if any field is malformed,
        # this raises rather than returning a bad payload downstream.
        return AgentRunResponse.model_validate(payload)
