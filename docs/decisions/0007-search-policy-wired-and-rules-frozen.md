---
type: decision
status: current
superseded_in_part_by: docs/decisions/0009-launch-with-orders-and-delivery-only.md
updated: 2026-10-04
summary: search_policy joins the production tools and the system rules widen to store policies; code renders the top hit verbatim; the rules, tool definitions and reply phrases are frozen from this commit until the M3 launch
---

# 0007: search_policy is wired in and the rules are frozen

Status: accepted (2026-10-04). One commit switches the rules, the tool schema, the reply phrases and the wiring together, because the gates break on any half state.

## Decisions

- **Third customer-facing tool.** `prompts/tools/search_policy.json` takes one `query` string. Its description names what it finds (store policies and frequently asked questions), not how it searches, so a hybrid retriever later needs no change to it.
- **Code renders the top hit word for word.** A `policy_found` result is answered with the first hit's `answer` from the knowledge base (`agent/policy_replies.py`); the model writes nothing. The public trace lists the hit ids in `knowledge`.
- **No hit becomes a handoff offer.** `policy_no_match` is answered with `sentences.policy_no_match` plus the handoff offer; a yes then runs the existing `handoff_to_human` path. An unreadable knowledge base gives the named fallback `policy_unavailable` with its own sentence and no offer.
- **Query words come from the customer's latest message.** `agent/search_guard.py` refuses a query whose non-stopword is not in that message, and one that holds an email or an order number.
- **A search stands alone in its call block.** Two different `search_policy` calls in one block, or one next to another tool, are rejected unexecuted with the code `one_search_at_a_time`, like a lookup that shares its block. A successful search ends the turn with the rendered reply, so the model never writes text after a search.
- **A message with an order number never searches.** It follows the order steps (ask for what is missing, or look up). Switching orders still drops the earlier order's facts.
- **A policy result is a fact source for its own turn only.** Red lines 1 and 2 count `search_policy` text as a source for the turn that called it; earlier turns' policy results support nothing. Same-turn mixing of policy text and order facts is a documented limit of the graders (`eval/README.md`).
- **The refusal sentence widens** to "orders, delivery and our store policies". The previous sentence stays an accepted refusal in the grader (`replies.decline_previous`), so older reports regrade unchanged; the rules before this change are `data/eval/previous_rules/rules-v8.md`.

## Freeze

From this commit until the M3 launch, three files are frozen, because the Gist artifact is trained on them and its manifest pins their hashes:

- `prompts/system_rules.md`
- `prompts/tools/*.json`
- `prompts/reply_phrases.json` (the rules quote its decline sentence; the grader and the agent read the rest)

Changing any of them changes `rules_version` or the tools hash, and means retraining the Gist, a new epoch in `eval/baseline.json` and new reports. These changes do not touch the freeze and need no retraining: knowledge-base entries, aliases and search parameters (`kb/`), web copy, runtime checks in `agent/`, the gateway.

## Consequences

- Hashes of the final rules and tools (Qwen3 tokenizer, from `gisting.prompt.fingerprint`): `rules_version` `65f9a4bf58d03aef` becomes `069d997a4d4eb24e` (rules sha256 `069d997a4d4eb24e10a5cb7b7dc274565f334d15c5f1b39db6413f2b01fefaa7`); the tools sha256 `1a19f792d4a935f4485e8b597d6efca0edbcd7ecfa0be515deba34b35e697d74` becomes `914da5a8d4761e3327cf1264b791e05ba5cb8e915f4be0786bc1362c80e32049`. The rules segment grows from 523 to 691 tokens and the tools segment from 395 to 525. Reports committed before this are from the old epoch: the token replay skips them, the regrade still runs.
- The freeze is pinned by `data/freeze/frozen-prompts-v1.json` (rendered rules sha256, the sha256 of every file in `prompts/tools/`, the sha256 of `prompts/reply_phrases.json`) and checked by `tests/prompt/test_prompt_frozen.py`, whose failure points here. A deliberate change edits that file in the same commit as the retraining.
- A Gist artifact trained before this commit fails manifest verification (`rules_sha256`, `tools_sha256`) and cannot load. Gist mode needs a retrain on the new rules; Full mode runs now.

## Erratum

The message of commit `5839762` gives the tools sha256 line wrongly: its old value is right only in the first 16 characters and the new value is missing. That commit's own values were `rules_version` `fbbcbd5550ec4ed4`, tools sha256 `28a1806efad61efac5d37b0ead5aa3506a693dfaca7ae62c077c8b06e4da7212`, 634 and 532 tokens. The step 3 wording and the tool description were then revised before the freeze; this record is authoritative.
