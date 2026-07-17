"""
demo.py — end-to-end demonstration. Run:  python scripts/demo.py

Exercises the agent over every provided sample case, then shows the approval
flow and the approval-boundary backstop. No server needed: it drives the
AgentHarness directly, so it doubles as a smoke test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as `python scripts/demo.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import load_env  # noqa: E402
from app.harness import AgentHarness, ApprovalRequiredError  # noqa: E402
from app.schemas import RunRequest  # noqa: E402
from app.state import RunState  # noqa: E402

# Honor .env (e.g. AGENT_PLANNER=llm) so the demo can run through the real LLM.
load_env()

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def line(char: str = "-", n: int = 78) -> None:
    print(char * n)


def show_run(resp) -> None:
    d = resp.decision
    print(f"  run_id     : {resp.run_id}")
    print(f"  status     : {resp.status.value}")
    print(f"  action     : {d.action.value}   (risk={d.risk_level.value})")
    print(f"  reason     : {d.reason}")
    if d.triggered_rules:
        print(f"  policies   : {', '.join(d.triggered_rules)}")
    print(f"  tool_calls : {[t.tool + ':' + t.status.value for t in resp.tool_calls]}")
    if resp.draft_po:
        po = resp.draft_po
        print(f"  draft_po   : {po.quantity} x {po.item} = {po.estimated_total:.0f} USD ({po.department})")


def main() -> None:
    harness = AgentHarness()
    cases = json.loads((FIXTURES / "sample_requests.json").read_text(encoding="utf-8"))

    line("=")
    print("PROCUREMENT APPROVAL AGENT — SAMPLE CASES")
    line("=")
    passed = 0
    for c in cases:
        resp = harness.run(
            RunRequest(user_id=c["user_id"], department=c["department"], message=c["message"])
        )
        ok = resp.decision.action.value in c["expected_behavior"]
        passed += ok
        print(f"\n[{c['id']}]  expected={c['expected_behavior']}  ->  {'PASS' if ok else 'FAIL'}")
        print(f"  message    : {c['message']}")
        show_run(resp)
    print()
    line()
    print(f"Sample cases: {passed}/{len(cases)} passed")
    line()

    # ---- Approval flow -----------------------------------------------------
    print("\n")
    line("=")
    print("APPROVAL FLOW — a human approves a hardware purchase")
    line("=")
    r = harness.run(
        RunRequest(user_id="u_002", department="engineering",
                   message="請幫工程部採購 2 台 MacBook Pro。")
    )
    print("\n1) Initial run:")
    show_run(r)
    print("\n2) Human calls POST /agent/runs/{id}/approve:")
    r2 = harness.approve(r.run_id)
    show_run(r2)
    print("\n   -> submit_to_erp appears in the trace ONLY after approval.")

    # ---- Guardrail C backstop ---------------------------------------------
    print("\n")
    line("=")
    print("GUARDRAIL C — direct submit_to_erp on an UNAPPROVED run is blocked")
    line("=")
    st = RunState(run_id="run_demo", user_id="u", department="engineering", message="x")
    try:
        harness._invoke_tool(
            st, "submit_to_erp",
            {"run_id": "run_demo",
             "draft_po": {"item": "MacBook Pro", "quantity": 1, "unit_price": 2500,
                          "estimated_total": 2500, "department": "engineering"}},
        )
        print("  BUG: submit_to_erp executed without approval!")
    except ApprovalRequiredError as exc:
        print(f"\n  Blocked as expected: {exc}")
        print(f"  Trace records the refusal: status={st.trace[-1].status.value}")

    print()


if __name__ == "__main__":
    main()
