---
type: decision
status: current
updated: 2026-10-05
summary: The serve failure store counts per session and per salted IP digest with a 24 h sliding TTL and decides locks itself, a compare is metered so only the excess of its Full turn is counted and each Gist exchange can be compared once, and the limits this leaves are written down
---

# 0012: serve failure store and compare metering

Status: accepted (2026-10-05). Amends 0008: the lock reply, the missing-digest rule and the compare rule.

## Context

0008 put the lookup-failure lockout in the serve process. A compare runs the Gist turn first and the Full turn second on the same message, and both must reach the same verdict without counting one failure twice.

## Decision

- **Two key kinds.** Session and salted IP digest each have their own capacity and a 24 h sliding TTL (the clock restarts at each failure). Once a key is at its limit nothing more is counted on it.
- **Eviction is named.** A key pushed out by capacity is counted and reported as the degraded reason `failure_store_evicted`.
- **The counter decides the lock.** The store implements the tools protocol (`failures`, `is_locked`, `record_failure`); a request gets a view of it.
- **Live view.** Reads and writes the store; remembers what this request first saw and how much it spent.
- **Replay view (Full turn of a compare).** Failures are metered: a Full failure first uses up what the Gist turn of the same exchange spent; only the excess is written, and failures others added in between are visible.
- **One compare per exchange.** Every committed Gist exchange can be compared once. Acceptance consumes it, so a timeout or crash also counts.
- **Missing or empty IP digest.** It goes to one shared `unknown` bucket (fail closed) and `ip_digest_missing` is reported once per request.
- **Limits** in `data/serve/limits.json`, per key kind: `ipFailureLimit` 20, `failureTtlS` 86400, `maxFailureKeys` 10000.

## Amends 0008

- A locked reply is its own `locked` status. It is not byte-identical to not-found or mismatch, as 0008 said.
- A lock depends only on failure counts, never on whether the order exists or the credentials were right, so it does not reveal that an order exists. `AGENTS.md` asks only that mismatch and not-found are byte-identical, and that still holds: an adversarial review found a wrong-email attempt on an existing and on a missing order identical in result and in the public trace.

## Consequences and known limits

- A compare lets a session verify up to twice its limit (extra verifications are at most the registered failures; the demo email is about 50 bits and not derivable). Exact limiting needs the Full turn to replay the tool results the Gist turn stored; that changes the agent and is a later order.
- When a compare comes with a different IP digest, the session key may be counted extra (fail closed).
- The IP key is a coarse signal of other sessions' failures from the same IP on the same day; a shared exit can be locked by others for a day.
- The copy "locked for this chat" is inexact on an IP lock. Changing copy needs the user's approval.
- `app.py` does not yet pass an IP digest. Until it does, every request lands in the `unknown` bucket and 20 failures lock the whole site. Before serve is exposed, the gateway digest header and its validation (charset, length, never equal to `unknown`) must be done.
- Checking the lock and then recording is not atomic; it relies on the gate's single worker (tested).
- Degradation is reported only through the `on_degraded` callback; wiring it to logs and `/health` is a separate order.
