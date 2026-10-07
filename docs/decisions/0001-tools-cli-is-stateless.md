---
type: decision
status: current
superseded_in_part_by: docs/decisions/0008-serve-process-holds-sessions-and-failure-lockout.md
updated: 2026-10-02
summary: The tools CLI handles one call per process, so lockout and cache live in the host, not in the CLI
---

# 0001: The tools CLI is stateless

Status: accepted

## Context

`python -m gisting.tools call lookup_order` handles exactly one call per process.
The per-session failure counter and the order cache are in-memory objects built
inside that process.

## Decision

- Each CLI invocation starts with a failure count of 0 and an empty cache.
  `Locked` cannot be reached through the CLI; it is only reachable when a
  long-lived host injects a counter that survives across calls.
- Lockout across calls is the host's job. Today the host is the agent process,
  which owns one counter per conversation. In M3 the counter moves to shared
  storage (the `FailureCounter` protocol is the seam).
- `tests/tools/test_lookup_cli.py::test_every_cli_call_starts_with_a_fresh_failure_count`
  pins this contract.

## Consequences

- A script that shells out to the CLI in a loop is not rate limited by the CLI.
  That is acceptable because the CLI is a pipeline stage and a debugging tool,
  not the public entry point; the gateway quota and the shared-storage lockout
  guard the public path.
