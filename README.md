# Procurement Approval Agent: Minimal Agent Harness

A lightweight enterprise procurement-approval agent. A user submits a
natural-language purchase request; the system safely decides whether to draft a
purchase order, route to human approval, reject, or ask for more information.

The point of this project is **not** the procurement logic (that is deliberately
simple). It is the **agent harness**: a runtime that executes an agent safely,
controllably, and auditably inside a backend, with explicit tool boundaries,
an approval boundary, and schema validation at every edge.

> Full design rationale is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
> How AI tools were used (and verified) is in [`docs/AI_USAGE.md`](docs/AI_USAGE.md).

---

## Quick start

Requires Python 3.11+ (developed on 3.14).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Run the demo (recommended first)

Drives all provided sample cases + the approval flow + the approval-boundary
backstop, with no server needed:

```bash
python scripts/demo.py
```

### Run the API server

The server runs in the foreground and takes over the terminal (it stays there
printing logs). Start it in one terminal:

```bash
uvicorn app.main:app
# interactive docs at http://127.0.0.1:8000/docs
# liveness probe:      GET http://127.0.0.1:8000/health
```

Leave that running and interact with it either from the browser docs or from a
**second terminal**.

**Option A: browser (`/docs`).** Open http://127.0.0.1:8000/docs. Under
`POST /agent/run` click "Try it out", pick a body from the **Examples** dropdown
(low-risk draft, hardware needing approval, missing info, or prompt injection),
and Execute. To test approval, run the **needs_approval_hardware** example, copy
the `run_id` from the response, open `POST /agent/runs/{run_id}/approve`, paste it
in, and Execute.

**Option B: terminal (`curl`), run from a second terminal while the server runs.**
This low-risk purchase returns a draft PO:

```bash
curl -X POST http://127.0.0.1:8000/agent/run \
  -H 'Content-Type: application/json' \
  -d '{
        "user_id": "u_001",
        "department": "marketing",
        "message": "請幫行銷部採購 3 個 Figma Enterprise 席次，總預算在 3000 美元以內。"
      }'
```

The response carries the decision, the draft PO (if one was created), and the
full tool-call trace (each entry also includes its validated input/output,
trimmed here):

```json
{
  "run_id": "run_xxxxxxxx",
  "status": "COMPLETED",
  "decision": {
    "action": "CREATE_DRAFT_PO",
    "risk_level": "LOW",
    "requires_human_approval": false,
    "reason": "Request matches policy and is within budget."
  },
  "draft_po": {
    "item": "Figma Enterprise Seat", "quantity": 3,
    "unit_price": 800.0, "estimated_total": 2400.0, "department": "marketing"
  },
  "tool_calls": [
    {"tool": "lookup_catalog", "status": "success"},
    {"tool": "check_policy", "status": "success"},
    {"tool": "create_draft_po", "status": "success"}
  ]
}
```

To test the approval flow, first create a run that *needs* approval (the hardware
message returns `status: AWAITING_APPROVAL`), then pass **its** `run_id` to the
approve endpoint. This snippet captures the `run_id` for you, so there is no
placeholder to replace:

```bash
# 1) create a run that needs approval and read back its run_id
RUN_ID=$(curl -X POST http://127.0.0.1:8000/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"u_002","department":"engineering","message":"請幫工程部採購 2 台 MacBook Pro。"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['run_id'])")

# 2) approve that run
curl -X POST http://127.0.0.1:8000/agent/runs/$RUN_ID/approve
```

> Approving only works on a run that is actually awaiting approval. Approving a
> low-risk (already `COMPLETED`) run returns `409` by design. Run state is kept in
> memory, so it is cleared whenever the server restarts.

### Run the tests

```bash
pytest -q
```

---

## What it does: the four decisions

| Decision | When | Sample case |
|---|---|---|
| `CREATE_DRAFT_PO` | in policy, within budget & threshold | 3 Figma seats |
| `NEED_HUMAN_APPROVAL` | restricted category, > $5000, over the requester's stated cap, over department budget, or bypass attempt | 2 MacBooks / 10 Figma / injection |
| `ASK_CLARIFICATION` | cannot price the request (missing item or quantity) | "buy Oracle" |
| `REJECT` | reserved for hard policy violations | (not triggered by samples) |

All five cases in `fixtures/sample_requests.json` pass (`python scripts/demo.py`).

---

## Configuration: rule-based or real-LLM planner

The planner is chosen by the `AGENT_PLANNER` environment variable. The default is
deterministic and needs no API key.

```bash
# default: deterministic rule-based planner
AGENT_PLANNER=rule uvicorn app.main:app

# real LLM (NVIDIA NIM, OpenAI-compatible): needs `pip install openai` + a key
AGENT_PLANNER=llm LLM_MODEL=meta/llama-3.3-70b-instruct \
  NVIDIA_API_KEY=nvapi-... uvicorn app.main:app
```

Easier: copy `.env.example` to `.env`, fill in `NVIDIA_API_KEY`, and just run
`uvicorn app.main:app` — the app auto-loads `.env` (via `python-dotenv`). The
`LLMPlanner` drives NVIDIA's OpenAI-compatible endpoint with the `openai` SDK, so
pointing it at any other OpenAI-compatible provider is just a different
`NVIDIA_BASE_URL` + `LLM_MODEL`.

Both planners return the same schema-validated `ParsedIntent`, so safety is
identical: the gate still overrules whatever the planner proposes.

---

## Project structure

```
app/
  main.py            FastAPI app. Thin: parses HTTP, calls the harness, returns.
  harness.py         AgentHarness, the core runtime. All control lives here.
  planner.py         NL message -> ParsedIntent. RuleBasedPlanner + LLMPlanner behind one Protocol; make_planner() switches via AGENT_PLANNER.
  gate.py            ApprovalGate, the single authority; the decision ladder.
  tools/
    base.py          Tool ABC: name + input schema + requires_approval + run().
    registry.py      ToolRegistry, name -> tool; the dispatch seam.
    lookup_catalog.py / check_policy.py / create_draft_po.py / submit_to_erp.py
  schemas.py         Pydantic contracts at every boundary.
  state.py           RunState + execution trace + in-memory run store.
  fixtures.py        Loads catalog / policies / budgets once.
fixtures/            Provided mock data (unmodified).
scripts/demo.py      End-to-end demonstration / smoke test.
tests/               pytest suite (planner, gate, tools, harness, guardrails).
docs/                ARCHITECTURE.md, AI_USAGE.md
```

---

## Key design decisions

- **Planner decides, harness enforces.** The planner's output is an *untrusted
  proposal*; the gate can overrule it and the harness holds all authority. This
  is why a real LLM planner can be dropped in without weakening safety.
- **One controlled path to every tool** (`AgentHarness._invoke_tool`): the single
  place input is validated, authorization is enforced, and the trace is written.
- **Approval boundary is code, not a prompt.** `submit_to_erp` is flagged
  `requires_approval=True`; the harness refuses it until the run is approved,
  even if a prompt injection explicitly demands it.
- **Prompt injection is defeated structurally.** The user `message` is data that
  gets parsed and checked against policy; it is never executed as instructions.

## Notes

- `requirements.txt` uses lower-bound pins (`>=`) so the project installs on the
  newest Python (3.14) where older pinned pydantic wheels are unavailable.
- The run store is in-memory (a dict). In production it would be a database; the
  `RunStore` seam makes that swap local.
