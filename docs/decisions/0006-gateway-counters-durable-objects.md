---
type: decision
status: current
updated: 2026-10-04
summary: Gateway quota counters live in SQLite-backed Durable Objects, one object per key, in a separate Worker bound to Pages; narrow-to-wide saturating counts, deadline, coarse daily IP digest; fake namespace in tests
---

# 0006: gateway counters use Durable Objects

Status: accepted. Implements the shared-storage seam named in 0001 and 0002.

## Platform facts (read 2026-10-04 from developers.cloudflare.com)

- **Free plan works** (`/durable-objects/platform/pricing/`): SQLite backend only. Per day: 100,000
  requests, 100,000 rows written (`kv.put`, deletes and `setAlarm()` count). Over a limit operations
  fail; reset 00:00 UTC.
- **Pages cannot host the class** (`/pages/functions/bindings/`): a separate Worker defines it, Pages
  binds it with `script_name`. The class is declared by an `exports` map (`storage: sqlite`).
- **Atomicity**: `ctx.storage.kv` is synchronous and an object is single-threaded: no `await` between
  a read and a write means no interleaving.

## Decisions

- **One object per counter key** (`idFromName`), `increment(ttlSeconds, limit)` only. Kinds: `session`,
  `full`, `ip`, `site`. Keys are a whitelist `kind(:[A-Za-z0-9_-]+)+` of bounded length; the stored value
  is `{count, expiresAt}`: no address, message, order number or email.
- **Increment, then judge, narrow to wide.** The object adds one and returns the count in one
  synchronous step; the gateway refuses when `count > limit`. Checks run `full`, `session`, `ip`, `site`
  and stop at the first refusal, so a request a narrow scope refused never spends a shared one. At
  `limit` the object stops writing and answers `limit + 1`: writes per key are capped at `limit`.
- **Expiry is lazy and swept.** A window starts at the first increment and lasts `counterTtlSeconds`;
  an expired record counts as empty even if the alarm is late; the alarm calls `deleteAll()`. `ip` and
  `site` keys carry the UTC date and need `counterTtlSeconds >= 86400`; a data test fails below that.
- **Fail closed with a name.** Unreachable, throwing, timed-out or malformed calls become
  `CounterFailure(reason, {cause})`: `durable_object_unreachable`, `_bad_reply`, `_timeout` or
  `counter_key_rejected`, then `CounterUnavailable{reason, causeName}`; nothing is generated and the
  answer is 200 `{served_by: "replay", reason: "offline", turns}` (a spent site allowance: `"quota"`).
  The log keeps the reason and `error.name` of the cause, never message or key. Calls have a deadline
  (`counterTimeoutMs`); late results are discarded; no retry, no isolate-memory fallback.
- **Coarse, daily address digest.** IPv6 is reduced to its /64 (IPv4 whole; IPv4-mapped counts as IPv4),
  and the UTC date is part of the HMAC input, so changing host bits does not dodge the cap and digests
  cannot be linked across days. Malformed values are digested as opaque strings.
- **Lookup-failure lockout is not here.** The gateway never learns whether a lookup matched: the lock is
  in the main server process, per session and per salted IP digest of gateway-forwarded traffic (a
  later ADR). Durable Objects count quota only.
- **Tests use a fake namespace** over the real `CounterCore`; the thin shell is checked by hand with
  `wrangler dev`. `@cloudflare/vitest-plugin` was rejected (peers `vitest ^4.1`, ~50 MB).

## Consequences

- Files hold no account id or secret. At deploy time the Worker name `gisting-counter` must equal
  `script_name` in the Pages file, and that file's `name` (sample `gisting`) must become the real Pages
  project name. `.wrangler/` and `.dev.vars*` are git-ignored.
- **Not verified live.** A Pages Function calling a Durable Object of another Worker was run only locally
  (`wrangler pages dev` plus `wrangler dev`). A real deployment probe must pass before release.
- **Attack surface: draining the free quota.** A client past Turnstile costs 3 to 4 calls per request,
  so about 25,000 requests a day use up 100,000 and counters then fail until 00:00 UTC. Mitigations, each
  partial: the IPv6 /64 digest (done); an edge WAF rate-limit rule on `/api/chat`, set by the user at
  deploy (open to-do; the real defence against many addresses); the offline replay (done), so draining
  costs the live demo, not money or safety.
