# AI Usage

I built this project with an AI coding assistant (Claude Code). To be clear about
the division of labor: the assistant generated most of the code, while I owned
the requirement analysis, the design decisions, and the verification. The claim I
am making is not that I wrote every line by hand, but that nothing went into this
repository without me understanding it, running it, and being able to explain it.
This note describes how I kept control of what the tool produced.

## Understanding the problem first

Before writing any code, I had the assistant read the task description and all
four fixture files, then work each of the five sample requests by hand against
the actual numbers. Three Figma seats at $800 is $2,400, under the $5,000
threshold, so the request can be drafted. Ten seats is $8,000, over the
threshold, so it requires human approval.

That exercise is where the design came from, and it surfaced a subtlety I might
otherwise have missed: "buy Oracle" must be a clarification rather than a
rejection, because without a quantity the request cannot be priced. Completeness
therefore has to be checked before risk, and that ordering became the backbone of
the decision ladder.

## The design decisions were mine

At each design fork I was presented with the trade-offs and made the choice:
Python with FastAPI and Pydantic; a rule-based planner behind an interface so a
real LLM can replace it later; and, for the prompt-injection case, routing to
human approval rather than a hard rejection, which neutralizes the instruction
while keeping the request recoverable.

## Verifying the generated code

The assistant scaffolded the modules and wrote the first drafts of the schemas,
the four tools, the planner, the gate, the harness, the tests, and this document.
Producing that code is quick; the work that matters is what followed.

I ran everything rather than relying on inspection. The planner was tested against
all five sample messages, the gate logic was simulated against the expected
outcomes before it was wired into the harness, and the full harness was exercised
end to end. I then started the server and issued requests with curl, because a
function returning the correct dictionary and the HTTP service behaving correctly
are separate claims that require separate verification.

One example shows why this matters. The first version of the harness only looked
up the catalog when both the item and the quantity were present. For "buy Oracle,"
which has no quantity, it skipped the lookup and reported that the item was
missing, even though Oracle is in the catalog and only the quantity was absent.
The test still passed, because the final action (`ASK_CLARIFICATION`) was correct.
I caught the problem only by reading the demo output and noticing that the
clarification asked for information the user had already supplied. The fix was to
resolve the item whenever a query is present, so the clarification is precise.
This is the failure mode I watch for in generated code: not incorrect enough to
fail a test, but incorrect enough to produce a confusing result for a user.

A later pass turned up a similar case in the approval flow. When a human approves
a hardware purchase the run finishes and its status becomes `COMPLETED`, but the
decision it still carried read `NEED_HUMAN_APPROVAL`, with the reason "hardware
purchases require human approval." Every test passed, because the tests checked
the status and the tool trace, not the text of the decision. I only noticed by
reading the demo output and seeing a completed run that still claimed it was
waiting on a human. A downstream system reading that record would get two
contradictory signals. The fix reconciles the decision at the moment of approval:
the action becomes `CREATE_DRAFT_PO` and the approval requirement is cleared,
while the original reason and the triggered policy rule are kept so the record
still explains why the run was escalated in the first place. I pinned the new
behavior with an assertion in the approval test so the same inconsistency cannot
come back without a test failing.

For the security-sensitive behavior I did not rely on the code appearing safe.
The guarantee that `submit_to_erp` cannot run before approval is backed by a test
that invokes it directly on an unapproved run and asserts two things: that it is
refused, and that the refusal is recorded in the trace. A guardrail I cannot
demonstrate with a test is one I do not consider reliable.

This verification is captured in a 28-test suite. The value is not the count but
that the guarantees are pinned down, so a later change that breaks one fails
visibly rather than silently.
