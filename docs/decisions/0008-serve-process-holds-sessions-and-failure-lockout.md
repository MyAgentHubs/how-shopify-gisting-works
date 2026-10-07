---
type: decision
status: current
updated: 2026-10-05
summary: The serve process holds session history and the lookup-failure lockout in memory, keyed by session id and by the gateway's salted daily IP digest, with a 24 h TTL independent of session eviction
---

# 0008: the serve process holds sessions and the failure lockout

Status: accepted. Completes the "later ADR" named in 0006 and replaces the shared-storage plan in 0001 and 0002.

## Decisions

- **State lives in the serve process.** Session history and failure counts are in memory: one process, one
  main server, no standby backend (user decision). "Never in isolate memory" in `AGENTS.md` means a
  Cloudflare isolate (Pages Functions, Workers); the serve process is not one. That line was reworded in
  a separate commit with the user's consent: "docs: say where the lookup failure lockout lives in the
  security invariants".
- **Two keys, counted independently.** The session id, and the gateway's salted daily IP digest forwarded
  in a request header (never the body, so the request contract and generated schemas do not change). The
  session key keeps `failure_limit_per_session`; the IP key has its own `ipFailureLimit` in
  `data/serve/limits.json`, set above the session limit so a shared exit address is not punished for one
  user. Either key at its limit locks the lookup; a lock is byte-identical to not-found and mismatch.
- **TTL 24 h, own store.** Failure counts are not held by `SessionStore`, so evicting or resetting a
  session never zeroes them. A capacity cap applies; when full the oldest key is evicted and a named
  degraded counter is incremented.
- **The IP key rolls over at 00:00 UTC.** The digest includes the UTC date (0006 privacy trade-off), so a
  new day starts a new IP key. Accepted; 0006 is unchanged. A missing or malformed digest header means the
  request is counted by session only, with `fallback_reason` recorded and counted.
- **Restart clears everything.** Accepted as a known limitation: one main server, rare restarts.
- **Compare.** The Full compare turn only reads the counts, and reads the values from before the Gist
  turn of the same message, so both modes reach the same verdict and nothing is counted twice.
- **Verification still runs before any cache read** (unchanged from 0002).

## Superseded in part

- 0001: the plan to move the counter to shared storage in M3. The host is the serve process; the
  `FailureCounter` seam is kept. The one-call-per-process CLI contract stands.
- 0002: "per session and does not expire". Lockout is now per session and per IP digest, with a 24 h TTL.
  Cache key, residual oracles and the deferred timing channel stand.

## Consequences

Each is a separate work order:

- tools and agent: a deps factory that injects a failure store keyed by session and IP digest.
- serve: the failure store (TTL, cap, eviction counter) and `ipFailureLimit` plus TTL and cap in
  `limits.json`.
- serve and gateway: the digest header, its validation, and the gateway forwarding it.
- runner: pass the digest and read-only counts for the compare path.
- `__main__` start order: check the secrets, bind the port, load the model, set ready.
- `AGENTS.md` rewording: done, in the commit named above.
