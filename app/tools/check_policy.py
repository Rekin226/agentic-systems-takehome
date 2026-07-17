"""
check_policy, evaluate a priced request against company policy.

This tool reports risk; it does not decide the final action. It answers:
"given this category, amount, and injection flag, which policy rules fire and
is human approval required?" The ApprovalGate consumes this to pick the action.

Keeping risk-reporting (tool) separate from action-selection (gate) means the
policy rules live in exactly one place and are trivially testable.
"""

from __future__ import annotations

from app.fixtures import fixtures
from app.schemas import CheckPolicyInput, CheckPolicyOutput, RiskLevel
from app.tools.base import Tool


class CheckPolicyTool(Tool):
    name = "check_policy"
    input_model = CheckPolicyInput
    requires_approval = False

    def run(self, payload: CheckPolicyInput) -> CheckPolicyOutput:
        triggered: list[str] = []
        reasons: list[str] = []

        # policy_004, explicit bypass / policy-override attempt.
        if payload.injection_detected:
            triggered.append("policy_004")
            reasons.append("Request attempts to bypass approval or company policy.")

        # policy_002 / policy_003, restricted categories require human approval.
        if payload.category in fixtures.restricted_categories:
            if payload.category == "hardware":
                triggered.append("policy_002")
                reasons.append("Hardware purchases require human approval.")
            elif payload.category == "enterprise_software":
                triggered.append("policy_003")
                reasons.append("Enterprise software licenses require human approval.")
            else:
                reasons.append(f"Restricted category '{payload.category}' requires approval.")

        # policy_001, amount over threshold requires human approval.
        if payload.estimated_total > fixtures.approval_threshold:
            triggered.append("policy_001")
            reasons.append(
                f"Amount {payload.estimated_total:.0f} exceeds threshold "
                f"{fixtures.approval_threshold:.0f} USD."
            )

        requires_approval = len(triggered) > 0
        if payload.injection_detected:
            risk = RiskLevel.HIGH
        elif requires_approval:
            risk = RiskLevel.MEDIUM
        else:
            risk = RiskLevel.LOW

        return CheckPolicyOutput(
            risk_level=risk,
            requires_human_approval=requires_approval,
            triggered_rules=triggered,
            reason=" ".join(reasons) or "Within policy.",
        )
