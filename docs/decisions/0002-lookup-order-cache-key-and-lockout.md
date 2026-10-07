---
type: decision
status: current
superseded_in_part_by: docs/decisions/0008-serve-process-holds-sessions-and-failure-lockout.md
updated: 2026-10-02
summary: lookup_order caches by order number only, counts lockout per session without expiry, and accepts named residual oracles
---

# 0002: lookup_order cache key, lockout scope and accepted residual oracles

Status: accepted

## Decisions

- **Cache key is the order number only.** The input email is checked against the
  HMAC email before the cache is read, so a cache read happens only for a caller
  who already knows the one valid email for that order. An email digest in the
  key would add nothing. The email read back from Shopify is still compared with
  the input on every call, including cache hits.
- **Lockout is counted per session and does not expire yet.** Every no-match
  (malformed, out of range, mismatch, not found, not a demo order) counts; matches
  and upstream errors do not. Lock duration and shared storage arrive in M3.
- **`unavailable` is a residual oracle, accepted.** It can only be produced after
  the HMAC check passes, so it tells a caller who already holds a valid email that
  Shopify is failing. It reveals nothing about orders for callers without one.
- **Timing side channel is deferred to M3.** A wrong email returns in about 5 us;
  a correct email reaches Shopify and takes about 100 ms. The gap tells an attacker
  that a guessed email was right. Mitigation (uniform delay or response shaping)
  belongs at the gateway in M3.
