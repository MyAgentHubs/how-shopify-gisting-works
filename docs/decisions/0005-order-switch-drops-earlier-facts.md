---
type: decision
status: current
updated: 2026-10-04
summary: When the customer moves to another order, earlier orders' text leaves the model input and the new order must be looked up afresh; the internal trace records each model input so the canary grader can scan it
---

# 0005: an order switch drops earlier facts

Status: accepted (2026-10-04). Commits `0d408cc`, `d73d4c7`, `34bbe08`, `f0d826b`, `d995cd3`, `539c38f`.

## Decisions

- **A switch is read from the customer's own messages.** `src/gisting/agent/context.py` walks
  the user messages and tracks the last order number and email. A new order number, compared
  after `parse_order_name` normalisation, or a new email (case-folded) starts a new segment.
  A bare number counts only inside the lookup range; a `#`-prefixed number counts anywhere,
  so a follow-up about `#9999` is a switch. When the order changes, the last email stays known.
- **Earlier segments that showed facts are dropped.** A segment shows facts when it holds a
  `ToolMessage` with an order number, or an assistant message that is not a tool call and is
  not one of the neutral replies (asks, refusals, fallbacks, failure replies), sent while the
  segment was armed (order number and email both known). Such a segment is replaced before
  the model sees it: user and plain assistant messages become the placeholder `context_drop.placeholder`
  in `prompts/agent_policy.json`; `ToolMessage`s and assistant messages with `tool_calls` are removed.
  The latest segment is never dropped. Segments with neutral replies only are kept, so the
  customer can retry after a wrong email.
- **The new order is looked up afresh.** No fact of the earlier order remains to answer
  from, so the model must call `lookup_order`, which verifies number and email as usual.
- **The internal trace records the model input.** Each model call stores `input_messages`
  (after the drop), so a grader can see what the model saw, not only what it said.
- **The canary grader scans six places** (`src/gisting/eval/canary.py`): each model input,
  each model output, the answer, the public trace, the headers and the cache keys. Any
  forbidden canary there fails with `canary_leak:<order>:<where>`; an unknown order fails
  with `canary_unknown`.
- **One call per turn for the same tool and arguments.** A repeat is not run again; the
  first result is reused and traced as `reused`, so two handoffs in one output open one ticket.
- **Model text may not state a time it was not given.** A month-day date, weekday, relative time
  word, duration (`1-5 business days`) or number of three digits or more (`prompts/time_words.json`)
  must come from the customer's own messages, this turn's tool results, the ask templates or an
  earlier assistant reply that is still in the model input after the drop (so a code-rendered
  status line can be repeated, and a dropped segment supports nothing); a question is exempt. Otherwise the text becomes the ask or the fallback and the trace records
  `unsupported_time_claim`. Code-rendered replies skip the check (`src/gisting/agent/time_claims.py`).

## Consequences

- Property tests (`tests/agent/test_agent_unauthorized_walk.py` and `..._forged.py`) walk
  wrong emails, missing orders, lockout, switches and forged tool blocks and assert that no
  turn shows data of an order it did not verify.
- Known limit: the production CLI keeps no tool history, so the switch and the shown-facts test
  work on text. An order number or email the customer never wrote cannot start a segment.
- `context_dropped` (message and segment counts) lives in the internal trace only; the public trace carries no flag, so it cannot hint that an earlier order was discussed.
