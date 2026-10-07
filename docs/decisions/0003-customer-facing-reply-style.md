---
type: decision
status: current
superseded_in_part_by: docs/decisions/0004-code-renders-customer-replies.md
updated: 2026-10-03
summary: Customer replies are plain, short and answer-first, internal states are translated by one table, incomplete order questions are always asked back, and the grader enforces readability from data; who produces the reply is now decided by 0004
---

# 0003: customer-facing reply style

Status: accepted (user decision, 2026-10-03). Partly superseded by 0004: the style rules
below still hold for every text the code renders, but "who produces the reply" (the model
words it from the rules) and the four-sentence limit for three fixed lines now follow 0004.

## Decisions

- **Plain text only.** No markdown (`**`, headings, list markers, backticks, links).
- **Internal states are translated by one table.** `prompts/reply_phrases.json` maps
  every `fulfillment_status` and `transport_status` value to the words a customer
  sees. The rules only render that table; replies never show capitalised enum names,
  field names, "tool", "status" or "Shopify".
- **A failed delivery is stated and a human is offered.** No advice to contact the
  carrier (Test Parcel is fictional).
- **Answer first, then the key facts.** Key facts are the status and, when the tool
  result has them, the carrier, tracking number and estimated date. A date is written
  as a month and day ("October 5"), marked "expected" or "estimated", never with a
  time. Without an estimated date no expected, estimated, scheduled or will-arrive
  wording appears. Without a tracking number the reply says the details are not
  available yet.
- **Ask for the missing item only.** Three fixed sentences (both, email, order number)
  live in the same data file; the rules, the agent templates and the grader all read
  it. Any order-related message without both inputs gets one of them, never a refusal.
- **Easy to read.** The first sentence carries the answer, each sentence is short,
  the whole reply has at most four sentences, nothing is repeated. The word limit lives in
  `data/eval/grader-v1.json` (`style`); the sentence limits moved to `prompts/reply_phrases.json`
  (`limits`) under 0004.

## Consequences

- The rules hash covers the rendered rules text (template plus data), so editing the
  table changes `rules_sha256` and invalidates trained Gist artifacts.
- `data/eval/previous_rules/rules-v4.md` keeps the previous rules for the leak check.
- Each status gets one full reply line in the rules (the table words plus the fact
  sentences), because a 1.7B teacher follows a lookup line far better than prose
  conditions. The rules grew from 501 to 1183 tokens, so `max_len` in
  `data/gist/hparams.json` is 2048 (1024 would skip every training example).
- The one-line `needs_customer_input` status in the rules is gone: the guard answers
  with a template and the model never sees that status.
