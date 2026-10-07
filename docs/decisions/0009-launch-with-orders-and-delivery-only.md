---
type: decision
status: current
updated: 2026-10-04
summary: The first launch serves orders and delivery only; the rules, tool definitions and reply phrases return to their pre-search_policy content so the k16-v8 Gist loads again, and the policy search stays in the repository, dormant
---

# 0009: launch with orders and delivery only

Status: accepted (2026-10-04). Reverses the production wiring, the rules switch and the freeze of 0007; the knowledge base and the search code of 0007 stay.

## Decision

- **Orders and delivery only.** Production tools are `lookup_order`, `handoff_to_human` and `send_shipping_reminder`. A `search_policy` call from the model is an `unknown_tool` and never runs.
- **Content returns to commit `d6a4654`** (the parent of `5839762`) for `prompts/system_rules.md`, `prompts/reply_phrases.json`, `prompts/agent_policy.json`, `src/gisting/agent/cli.py`, `data/eval/grader-v1.json` and `src/gisting/eval/data.py`, as new content in a new commit, not as a `git revert`: eval case lines stay append-only and 0007 stays on record.
- **Why.** After the K1b retrain, red line 4 failed in both modes: `final` Full 39 / 230, Gist 36 / 230, mostly off-topic or injection messages answered with a `search_policy` call. Old cases that passed under the earlier rules failed this time: Full 13, Gist 13.
- **The old Gist loads again.** Artifact `artifacts/gist/k16-v8-2026-10-03/k16-v8-seed20261002/` has `gist_sha256` `a41e307cfe017300261c6e628d749bbf64922e6a0e34e880a5b6de8f5f3063a9`, `rules_sha256` `65f9a4bf58d03aef88fb884f3eb9c6aa79551d2ca7394c92bd440f90da531a45` and `tools_sha256` `1a19f792d4a935f4485e8b597d6efca0edbcd7ecfa0be515deba34b35e697d74`. The rendered rules and the tools segment (Qwen3 tokenizer) of this commit hash to the same values.

## Freeze

- The freeze moves to `data/freeze/frozen-prompts-v2.json`, read by `tests/prompt/test_prompt_frozen.py`. It pins the rendered rules, `prompts/reply_phrases.json` and the files in `prompts/tools/`, and records the v8 artifact. `frozen-prompts-v1.json` stays as history and is no longer read.
- `prompts/tools/search_policy.json` moved to `prompts/deferred/search_policy.json`. Nothing loads that directory in production; `tests/prompt/test_prompt_deferred.py` keeps it a valid tool schema and fails if a source file names the directory.
- `data/eval/previous_rules/rules-v9.md` is the rendered rules of 0007, added to the leak check so reports from that epoch regrade unchanged. `rules-v8.md` is removed because it equals the current rules.

## Dormant, kept

`kb/` and `src/gisting/kb/`, `src/gisting/tools/search_policy.py`, and in `src/gisting/agent/` the policy modules (`policy_replies.py`, `search_guard.py`, `search_turn.py`, `crowding.py`, `knowledge.py`). `crowding.py` is still in use for `lookup_order`; only its search branch is unreachable in production. Their tests run against fakes and synthetic knowledge. The public trace field `knowledge` stays and is always `[]`. `policy_no_match` and `policy_unavailable` sentences are out of `reply_phrases.json` and return with the wiring.

## Later

- Policy answers come after launch, through code-level routing (a retrieval threshold, hybrid retrieval) instead of a model decision on every message, then a new rules epoch and a retrain.
- Retrain traps: `src/gisting/training/dataset.py` generates policy samples unconditionally, and `data/gist/templates.json` holds policy families. Retraining on the current rules must exclude both first.
- Evaluation: the 40 policy control cases have no `search_policy` to call, so they should be judged "not applicable in this version" by the tool set. A separate commit implements that and needs the user's confirmation; this record only notes it.
