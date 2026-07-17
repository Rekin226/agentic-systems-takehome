"""
gate.py: the ApprovalGate, the single authority that selects the final action.

It consumes signals (never raw user text) and applies the precedence ladder:

    1. incomplete request         -> ASK_CLARIFICATION     (Case 4)
    2. injection / bypass attempt -> NEED_HUMAN_APPROVAL    (Case 5)  [flag neutralized]
    3. policy requires approval   -> NEED_HUMAN_APPROVAL    (Case 2 hardware, Case 3 amount)
    4. over requester's stated cap-> NEED_HUMAN_APPROVAL
    5. over department budget     -> NEED_HUMAN_APPROVAL
    6. otherwise                  -> CREATE_DRAFT_PO        (Case 1)

Order matters: completeness is checked before risk, because you cannot assess
risk on a request you cannot even price (that is why "buy Oracle" with no
quantity is ASK_CLARIFICATION, not a category rejection).

This is pure decision logic, no I/O, no side effects, so it is trivially
unit-testable, and it is the natural place an auditor would read to understand
"how does this system decide?".
"""

from __future__ import annotations

from typing import Optional

from app.schemas import (
    Action,
    CatalogItem,
    CheckPolicyOutput,
    Decision,
    ParsedIntent,
    RiskLevel,
)


class ApprovalGate:
    def decide(
        self,
        intent: ParsedIntent,
        catalog_item: Optional[CatalogItem],
        estimated_total: Optional[float],
        policy: Optional[CheckPolicyOutput],
        remaining_budget: Optional[float],
    ) -> Decision:
        # 1. Completeness, can we even price this request?
        missing = list(intent.missing_fields)
        if catalog_item is None and "item" not in missing:
            missing.append("item")  # planner had a guess, but catalog couldn't resolve it
        if missing:
            return Decision(
                action=Action.ASK_CLARIFICATION,
                risk_level=RiskLevel.LOW,
                requires_human_approval=False,
                reason=f"Missing required information: {', '.join(sorted(set(missing)))}.",
            )

        # From here on, policy is guaranteed to exist (we priced the request).
        assert policy is not None and estimated_total is not None

        # 2. Prompt injection / explicit bypass, never auto-execute.
        if intent.injection_detected:
            return Decision(
                action=Action.NEED_HUMAN_APPROVAL,
                risk_level=RiskLevel.HIGH,
                requires_human_approval=True,
                reason=(
                    "Request attempts to bypass approval/policy. The override "
                    "instruction is ignored; routing to human review."
                ),
                triggered_rules=policy.triggered_rules or ["policy_004"],
            )

        # 3. Policy-driven approval (restricted category or over threshold).
        if policy.requires_human_approval:
            return Decision(
                action=Action.NEED_HUMAN_APPROVAL,
                risk_level=policy.risk_level,
                requires_human_approval=True,
                reason=policy.reason,
                triggered_rules=policy.triggered_rules,
            )

        # 4. Requester's own stated cap ("...under 3000"). If the priced total
        # blows past the limit the user themselves set, don't silently draft it;
        # the request conflicts with its own constraint, so route to a human.
        if intent.budget_cap is not None and estimated_total > intent.budget_cap:
            return Decision(
                action=Action.NEED_HUMAN_APPROVAL,
                risk_level=RiskLevel.MEDIUM,
                requires_human_approval=True,
                reason=(
                    f"Estimated total {estimated_total:.0f} exceeds the requester's "
                    f"stated budget cap {intent.budget_cap:.0f} USD."
                ),
            )

        # 5. Budget guard, request exceeds the department's remaining budget.
        if remaining_budget is not None and estimated_total > remaining_budget:
            return Decision(
                action=Action.NEED_HUMAN_APPROVAL,
                risk_level=RiskLevel.MEDIUM,
                requires_human_approval=True,
                reason=(
                    f"Estimated total {estimated_total:.0f} exceeds remaining "
                    f"{intent.department} budget {remaining_budget:.0f} USD."
                ),
            )

        # 6. Safe & compliant, create the draft.
        return Decision(
            action=Action.CREATE_DRAFT_PO,
            risk_level=RiskLevel.LOW,
            requires_human_approval=False,
            reason="Request matches policy and is within budget.",
        )
