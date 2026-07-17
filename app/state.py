"""
state.py: the state of a single Agent Run, plus a small in-memory store.

RunState carries everything one run accumulates: its status, the decision, the
draft PO (if any), and the execution trace (every tool call). The harness owns
and mutates this object; nothing else does.

The RunStore is a process-local dict. In production this would be a database;
for the take-home it is enough to support the optional approval flow
(POST /agent/runs/:id/approve needs to find a run again later).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.schemas import Decision, DraftPO, RunStatus, ToolCall


@dataclass
class RunState:
    run_id: str
    user_id: str
    department: str
    message: str
    status: RunStatus = RunStatus.NEEDS_CLARIFICATION  # provisional until decided
    decision: Optional[Decision] = None
    draft_po: Optional[DraftPO] = None
    candidate_po: Optional[DraftPO] = None  # prepared PO, used by the approval flow
    trace: list[ToolCall] = field(default_factory=list)
    approved: bool = False  # flipped only by the explicit approval flow

    def record(self, call: ToolCall) -> None:
        """Append a tool call to the execution trace."""
        self.trace.append(call)


class RunStore:
    """Process-local run registry. Swap for a DB in production."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def save(self, state: RunState) -> None:
        self._runs[state.run_id] = state

    def get(self, run_id: str) -> Optional[RunState]:
        return self._runs.get(run_id)


run_store = RunStore()
