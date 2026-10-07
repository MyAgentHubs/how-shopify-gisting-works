---
type: decision
status: current
updated: 2026-10-03
summary: Customer-visible facts and fixed phrases are rendered by code from the approved copy; the model only judges what to do; Gist trains on decisions only; three fixed lines may have five sentences
---

# 0004: code renders customer replies

Status: accepted (user decision, 2026-10-03). Supersedes 0003 for how replies are produced and for the sentence limit; the style rules of 0003 still hold for the rendered text.

## Decisions

- **Code renders every reply that states facts or a fixed phrase.** After `lookup_order`
  returns, the agent answers from `prompts/reply_phrases.json` and the tool result with
  no further model call: the status line (one per status, several parcels one sentence
  each, the note on the part not shipped, the reminder or handoff offer, the sentence
  with "but" for a missing tracking number) or the failure reply. Dates read "October 5",
  never with a year. The same holds for the confirmations after `handoff_to_human` and
  `send_shipping_reminder`, for a clear yes or no to an offer, for asks, and for the
  refusal. The internal trace records `reply_source` (`model`, `template`, `code`,
  `fallback`).
- **The model only judges.** Which tool to call, what is missing and must be asked,
  whether to refuse, whether the customer wants a human, and open talk such as thanks or a
  doubt about an offer. The rules keep the judgement and drop the wording (about 1265
  tokens down to about 520).
- **Runtime checks stay as the net under the model text.** A first-turn refusal in other
  words becomes the fixed refusal (the agent and the grader read one list,
  `prompts/refusal_words.json`); a refused order question becomes the ask for what is
  missing; a claim of a handoff or reminder, or a promise, with no tool result becomes one
  fixed sentence. Model text passes this net even after tools ran in the same turn.
- **A lookup result means code speaks.** `lookup_order` must stand alone in its block (a
  block joining it with other calls is rejected); once the turn has a lookup result the
  customer sees only the rendered reply, a template or a fallback, never model prose.
- **Shortcuts are whitelists.** The yes and no shortcuts after an offer fire only when every
  word is in the `consent_words` vocabulary of `prompts/agent_policy.json`. A sentence that
  merely contains a request pattern never fires the shortcut; it goes to the model, whose
  own `handoff_to_human` call is still allowed by the `requested` patterns.
- **Gist learns decisions, not wording.** Training samples are first turns only. The
  filter has a `decision` layer that checks the call, its arguments, the ask target, the
  refusal and the absence of invented facts or false confirmations, and ignores wording.
  A second-turn row has no decision, so that layer rejects it.
  The `raw` and `final` layers remain; the style grader judges the final text only.
  Training stays pure KL distillation from the Full-rules teacher, so the Gist cannot be
  better than the teacher's decisions.
- **Sentence limit.** Four sentences stay the limit, except the fixed lines for DELAYED,
  ATTEMPTED_DELIVERY and PARTIALLY_FULFILLED, which may have five. The limit lives in
  `prompts/reply_phrases.json` (`limits`), which both the reply renderer and the grader read.
  The words-per-sentence limit goes from 25 to 28 (user decision, 2026-10-03): the approved
  rendered sentences reach 26-27 words, and the limit was meant to bound long model-written ones.

## Consequences

- Changing a customer-facing sentence means editing `prompts/reply_phrases.json` only; no
  teacher run or Gist training is needed for a wording change.
- Rules hash changes, so earlier teacher files and Gist artifacts do not match the rules.
- The previous rules are kept in `data/eval/previous_rules/` for the leak check.
- Known risk: the reminder shortcut takes its order number from the customer's text and the
  previous offer, and the production CLI keeps no tool history. Before any real write (M3) the
  gateway must sign the history or the write must verify the order again.
