---
type: decision
status: current
updated: 2026-10-05
summary: serve bounds every wait on Shopify by the per-request deadline, turns any startup or loader failure and any crashed core thread into a typed redacted log event with exit code 1, and logs the Shopify reads that finished on 504 and 500 turns; the limits this leaves are written down
---

# 0015: serve request deadline, startup and crash logging

Status: recorded (2026-10-05) after the fact for commits 3709036..a7079de and the failed-turn lookups commit; the user has not reviewed it yet. Amends 0014 (its log field list). The watchdog and the kept throttle pause were added after the first review. Values come from `data/serve/limits.json`.

## Context

`totalDeadlineS` (20) only decided what the caller was told. A stalled Shopify call, a retry sleep or a throttle pause could keep the single worker busy long after the 504. A loader failure or a crashed thread could leave a process that looked alive.

## Decision: request deadline

- **One deadline per request, every wait clamped to what is left.** Covered: the token exchange, each HTTP call, the socket timeout (`min(shopifyTimeoutS, remaining)`, 6 s), each chunk of a body read, the retry sleep (`shopifyRetryS` 0.5 s, `shopifyReadAttempts` 2) and the throttle pause (at most `shopifyMaxPauseS`, 2 s).
- **A watchdog covers the whole exchange.** One timer per HTTP call, set to what is left of the deadline, shuts down every socket that call opened (connect, TLS, response headers, body). A read blocked on a server that drips headers or body fails at the deadline, not after the next per-receive timeout. The timer is cancelled and joined when the call ends, so no thread outlives it. A failure that arrives once the deadline has passed is raised through the clamp as the deadline, not returned as an uncertain reply.
- **Every tool call and model call checks first.** A code turn that never calls the model is also stopped before its next tool.
- **Per-request client.** The shared transport hands each request a read-only view (`bounded(clamp)`); the throttle pace is shared across requests.
- **Bounded transports are read-only.** The bounded view is used only on the read-only serve path, wrapped in `ReadOnlyTransport`. A failure after the deadline is always raised as the deadline and never returned as `Uncertain`, so a write must not go through a bounded view.
- **No redirects.** The Shopify client follows none: a 3xx on a read or a write is `NotExecuted` (`http_status`), never retried, and the `X-Shopify-Access-Token` header never leaves the admin host.
- **No new customer copy.** A request past its deadline ends as the existing `timeout` refusal (504).

## Decision: startup and crashes

- **Order.** env, assemble, bind, models, lookup, runner, ready.
- **Any exception in a stage, including `BaseException`,** becomes `startup_failed` with `stage`, `error_type`, `inner_type` (the loader's inner error class) and, for the env stage, `variables` (names only). The process exits 1 and the port is released.
- **Tool set checked once.** The frozen tool set and the schema names are compared when the runner is built; a mismatch fails the `runner` stage.
- **Exit code is forced.** The process leaves through `os._exit(code)`, so a daemon thread holding the stderr buffer cannot turn exit 0 into an abort.
- **Crashed thread.** An uncaught error in the loader, gate or listener thread logs `thread_crashed` with `thread`, `error_type` and `where` (never the message) and stops the process with exit 1. Other threads log the event only.

## Decision: failed turns log their reads

- Each request owns a lookup sink. A lookup call opens a slot when it starts and fills it when it ends: `shopify_ms`, `result_type`, `cache_hit`.
- 504 and 500 lines carry the slots as they stand when the response is decided, copied under a lock. A slot still open then is a read the deadline cut off. It is logged with the time spent so far, `result_type` `DeadlineExceeded` and `cache_hit` false, so no waiting and no race with the job thread.
- A lookup that ends in an exception (the deadline or anything else) records the exception class name as `result_type`, counts nothing against the failure lock and re-raises unchanged. Its `shopify_ms` runs from the start of the lookup call.
- A job that keeps running after the 504 cannot change a line already written.
- A request that never ran (busy, not_ready, compare_unavailable) logs none. No request id, session id, IP digest or order number is added.

## Amends 0014

0014's field list gains `inner_type` and `thread`. Events `startup_failed` and `thread_crashed` are named here. `lookups` appears on 200 lines and on 504 and 500 lines. The log still holds no order number, email, IP, digest, secret, canary or message text.

## Known limits

- Name resolution is not bounded by any timeout here; it depends on the system resolver (a `getaddrinfo` that slept 8 s under a 1 s deadline failed only at 8.01 s). A connect that tries several addresses one after the other can run past the deadline by up to (n-1) times the time left. The watchdog can only cut a socket that exists.
- The throttle pace carries over between requests, but each pause is at most 2 s. A pause cut short by the deadline keeps the unspent part for the next request; a pause longer than the cap is spent by one full sleep and then cleared.
- A cold request (first token exchange plus a hanging Shopify) can use the whole 20 s before the 504.
- A job past its 504 runs on until its next deadline check, and `/health` reports `loading` until it ends.
