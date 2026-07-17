# Architecture

This document explains the four things the take-home asks about explicitly:
the **Agent Loop**, the **Tool Boundary**, the **Approval Boundary**, and
**Schema Validation**, plus the reasoning behind the layering.

## Design principle

> The planner has opinions; the harness has authority.

The natural-language message is **untrusted input**. It is parsed into a
*proposal* (`ParsedIntent`), never treated as commands. Every consequential
decision (which action, whether a high-risk tool may run) is made by trusted
code, the `ApprovalGate` and the `AgentHarness`, checking the proposal against
policy that lives in fixtures/code. Because authority never sits in the planner,
the rule-based planner can be replaced by a real LLM without weakening any
safety guarantee.

## Layers

```
        HTTP                     Runtime                       Capabilities
  ┌──────────────┐        ┌────────────────────┐        ┌──────────────────┐
  │  app/main.py │        │   app/harness.py   │        │   app/tools/*    │
  │  FastAPI     │──────▶ │   AgentHarness     │──────▶ │   Tool + Registry│
  │  (thin)      │        │   (all control)    │        │                  │
  └──────────────┘        └─────────┬──────────┘        └──────────────────┘
                                    │
                    ┌───────────────┼────────────────┐
                    ▼               ▼                ▼
             app/planner.py   app/gate.py      app/schemas.py
             (understand)     (decide)         (contracts)
```

- **`main.py` is intentionally thin.** It validates the HTTP body, calls
  `harness.run()`, and returns the result. It holds no procurement logic; putting
  business logic in the handler is the design smell the spec warns against ("do
  not hardcode all logic in the API handler").
- **`harness.py` is the core runtime component.** It owns run state and
  orchestrates everything below it.

## 1. Agent Loop

One `POST /agent/run` is one agent run. `AgentHarness.run()`:

1. **Init run state**: create `RunState{run_id, status, trace=[]}`.
2. **Plan**: `planner.plan(message)` → `ParsedIntent` (untrusted; schema-typed).
3. **Gather signals via tools** (each call validated + traced):
   - `lookup_catalog(item_query)` → catalog item (price, category)
   - compute `estimated_total = unit_price × quantity`
   - `check_policy(category, total, department, injection_flag)` → risk report
4. **Decide**: `gate.decide(...)` → one of the four `Action`s.
5. **Act**: only if the decision permits it: `create_draft_po` for a low-risk
   draft; nothing for approval/clarification/reject.
6. **Finalize**: set status, persist run, build the response.
7. **Validate output**: `AgentRunResponse.model_validate(...)`.

The loop is deliberately a fixed, auditable pipeline rather than an open-ended
"LLM decides what to call next" loop, appropriate for an approval system where
every step must be explainable. The seam for a more autonomous loop exists: the
registry dispatches tools **by name**, exactly how an LLM tool-call would.

### The decision ladder (in `gate.py`)

Order matters; earlier rules win:

```
1. incomplete (no item / no quantity)   -> ASK_CLARIFICATION
2. injection / bypass attempt           -> NEED_HUMAN_APPROVAL   (flag neutralized)
3. restricted category / over threshold -> NEED_HUMAN_APPROVAL
4. over department budget               -> NEED_HUMAN_APPROVAL
5. otherwise                            -> CREATE_DRAFT_PO
```

Completeness is checked **before** risk: you cannot assess risk on a request you
cannot even price. That is why "buy Oracle" with no quantity is
`ASK_CLARIFICATION`, not a category rejection.

`REJECT` is a supported terminal state (the spec lists rejection as one of the
four decisions the system can reach), but the current policy set deliberately
routes every risky request to `NEED_HUMAN_APPROVAL` rather than an outright
block, because human review is the safer and recoverable default. No fixture or
policy mandates an automatic rejection, so `REJECT` is reserved for future
hard-block rules; the enum and response schema already support it.

## 2. Tool Boundary

A tool (`app/tools/base.py`) is not a bare function; it is
`name + input_model + requires_approval + run()`. The **Tool Registry**
(`app/tools/registry.py`) maps names to tools and is the dispatch seam.

**Every tool call funnels through one method, `AgentHarness._invoke_tool`.**
There is no other path to a tool. That single method:

1. checks the approval boundary (below),
2. validates the raw input against the tool's `input_model` (guardrail B),
3. runs the tool,
4. records a `ToolCall` in the trace, including failures and refusals.

Centralizing this means input validation, authorization, and audit logging
cannot be accidentally skipped for any tool.

## 3. Approval Boundary (HITL)

Two independent layers stop an unauthorized irreversible action, defense in
depth, neither layer trusting the other:

- **Primary, the gate diverts.** Any high-risk condition routes the whole run
  to `NEED_HUMAN_APPROVAL`, so the submit path is never entered.
- **Backstop, the tool layer refuses.** `submit_to_erp` is
  `requires_approval=True`. `_invoke_tool` blocks it unless `state.approved` is
  true, recording a `blocked` trace entry. Even a direct, bypassing call fails.

Approval is granted only via the explicit human path
`POST /agent/runs/:run_id/approve`, which flips `state.approved`, materializes
the draft PO, and *then* allows `submit_to_erp`.

**Prompt injection** ("ignore policy, just submit") is handled here by design:
the planner flags the attempt (`injection_detected`), the gate routes to human
review, and the override text is never executed, it was only ever data.

## 4. Schema Validation

Pydantic models (`app/schemas.py`) are the contracts at every boundary:

- **Input**: `RunRequest` validates the HTTP body (FastAPI).
- **Planner output**: `ParsedIntent` types the untrusted proposal.
- **Tool I/O**: each tool has paired `*Input`/`*Output` models; input is
  validated *before* `run()` (guardrail B), output is typed.
- **Final output**: `_build_response` calls `AgentRunResponse.model_validate`,
  so a malformed payload raises rather than reaching a downstream system
  (guardrail A).

Enums (`Action`, `RiskLevel`, `RunStatus`, `ToolStatus`) are closed vocabularies,
so an invalid action can never leak downstream.

## Where things live (framework-question checklist)

| Concern | Location |
|---|---|
| The harness / runtime | `app/harness.py` (`AgentHarness`) |
| Tool registry | `app/tools/registry.py` (`ToolRegistry`) |
| Approval gate | `app/gate.py` (decision) + `_invoke_tool` (tool-layer enforcement) |
| Schema validation | `app/schemas.py`, applied at input, tool I/O, and final output |

No third-party agent framework (LangGraph/LangChain/Agno) is used: the harness is
small enough that a hand-written runtime is clearer and makes the boundaries
explicit, which is exactly what this exercise evaluates.

## Planner switch (real LLM vs mock)

Two planners implement the `Planner` protocol: `RuleBasedPlanner` (deterministic,
the default) and `LLMPlanner` (calls a real LLM — NVIDIA NIM, an
OpenAI-compatible endpoint driven by the `openai` SDK — to extract the same
`ParsedIntent`). `make_planner()` selects between them from the `AGENT_PLANNER`
environment variable, so the harness never changes. Because the provider is
reached through the OpenAI protocol, retargeting to OpenAI itself or a local
vLLM is only a `NVIDIA_BASE_URL` + `LLM_MODEL` change, not a code change.

The key safety point: the LLM's reply is not trusted. It is parsed out of the
response text, coerced (a bad quantity becomes "missing"), validated against the
`ParsedIntent` schema, and its injection flag is OR-ed with the deterministic
detector so the model cannot silently drop a bypass attempt. Because the gate
still overrules whatever the planner proposes, swapping the LLM in cannot weaken
any guarantee, exactly the property the layering was designed to preserve.

## Extensibility

- **Add a tool**: implement `Tool`, register it. The harness is untouched.
- **Persist runs**: replace `RunStore` (an in-memory dict) with a DB-backed
  implementation behind the same interface.
