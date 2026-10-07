---
type: decision
status: current
updated: 2026-10-06
summary: Refresh stale demo ETAs by appending a same-status fulfillment event, verify writes by read-back without retries, and report same-state set-state requests as skipped.
---

# 0020: refresh stale demo ETAs by event

Status: accepted (2026-10-06).

## Context

Demo order ETAs were written once on 2026-10-02 and went stale. Calling `set-state` with the existing state was a silent no-op because pending steps checked event types only, yet the command reported the order as applied.

## Decision

- `refresh-eta` appends one fulfillment event with the current status, `happenedAt = now`, and `estimatedDeliveryAt = now + the plan offset`. When an order was moved by `set-state` to a status different from its plan event, use the corresponding `set-state` offset.
- By default, skip fresh ETAs, orders without an ETA or an applicable offset, and ETAs whose planned target is itself past (the `DELAYED` scenario).
- The staleness threshold lives in `src/gisting/shopify/demo_distribution.json` under `refresh_eta` (`stale_grace_minutes`), rather than in code.
- Preserve the existing write guard: only `gisting-lab.myshopify.com` orders with `test == true` are writable; refresh also requires a matching plan entry and plan tag.
- Verify writes by reading the order back. Report a read-back mismatch as `mismatch`; never retry a mismatched or uncertain write. An uncertain outcome stops the batch for inspection.
- `set-state` reports an already-present requested state as `skipped_same_state`, rather than applied.

## Usage

Preview all stale plan orders or one order, then explicitly select orders or all stale plan orders for writing:

```sh
python -m gisting.shopify.demo_apply refresh-eta --all-stale --dry-run
python -m gisting.shopify.demo_apply refresh-eta '#1006' --eta-days 7 --force --dry-run
python -m gisting.shopify.demo_apply refresh-eta --orders '#1006,#1014'
python -m gisting.shopify.demo_apply refresh-eta --all-stale
```

`--eta-days N` overrides the plan offset with `now + N days`; N must be an integer in the inclusive range configured by `refresh_eta.eta_days_min` and `refresh_eta.eta_days_max` in `src/gisting/shopify/demo_distribution.json` (currently 1..30). It still skips fresh orders unless `--force` is supplied.

`--force` bypasses freshness only: missing ETA, current event, or applicable offset still yields `skipped_no_eta`. It works with a positional order or `--orders`, including dry runs; combining it with `--all-stale` is a usage error (exit `2`).

Choose exactly one selector: a positional order, `--orders`, or `--all-stale`. Dry runs read orders but do not write fulfillment events. JSON output contains `summary` counts and per-order `orders` results.

| Result | Meaning |
|---|---|
| `written` | The write succeeded and read-back confirmed the target ETA. |
| `would_write` | A dry run found an eligible ETA, including a fresh ETA with `--force`. |
| `skipped_fresh` | The current ETA is fresh and `--force` was not supplied. |
| `skipped_no_eta` | No ETA, current event, or applicable offset is available. |
| `skipped_past_by_design` | The planned target remains in the past; never applies with `--eta-days`. |
| `mismatch` | The write reported success but read-back did not match the target ETA. |
| `uncertain` | The write outcome is uncertain or its verification read failed; inspect before any further write. |
| `failed` | A read, timestamp, or write failed. |
| `refused` | The read was refused or the store, test-order, or plan guard rejected the order. |

Exit codes: `0` for successful writes, dry-run candidates, or skips; `1` if any result is `mismatch`, `uncertain`, `failed`, or `refused`; `2` for invalid usage or inputs.

Real-write behaviour against Shopify has not been verified yet: validation has used offline fakes only. Before a batch write, one approved live write on a single order must verify the real behaviour and read-back.
