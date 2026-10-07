---
type: decision
status: current
updated: 2026-10-06
summary: The release lock is data-driven and as built it checks the example emails, a production sitekey, price age, approved copy and the ja and ko review state; the research link is optional; the CLI carries its own lock; only an allowlist of public data is published
---

# 0018: release lock and public data, as built

Status: accepted (2026-10-06, user decisions of the same day, review of the page at f01526c). Replaces the "Release lock" section and the public-data bullet of 0016; nothing else in 0016 or 0017 changes.

## Context

0016 listed a lock that blocked on a placeholder research link and any copy file not `approved`, and said the whole `apps/web/data/` directory was published except two file patterns. The page has since shipped ja and ko as approved drafts, the research article is not written yet, and a review found the lock could be bypassed from the CLI.

## Decision: release lock

`web:release-check` reads its patterns and limits from `apps/web/data/release_lock.json`. A release is blocked while any of these holds:

- An example order email does not match the demo shape `^[a-z2-7]{10}@orders\.example\.com$`, or is the repeated-letter placeholder.
- `data/runtime.json` has no sitekey, one that is not shaped like a Turnstile site key, or one of Cloudflare's test keys (`1x`, `2x`, `3x` prefixes). A production sitekey is required.
- `data/pricing.json` was accessed more than 45 days ago, or on a future or malformed date.
- A copy file is not `approved`, or holds a string starting with `[PLACEHOLDER`.
- `ja` or `ko` has `native_review` other than `approved_draft` or `done`. Both ship as `approved_draft` until the user's native review; then they become `done`.
- A link in `data/links.json` is non-empty and not an `https://` address, or is a placeholder: `#pending`, `TODO` or `TBD` as a whole word, `PLACEHOLDER`, or any host whose label is `example`.

## Decision: optional research link

`research_article` may be empty. An empty link is not a finding and the page hides the button. `required_links` in the lock file names links that must exist; it is empty today.

## Decision: where the lock runs

`cli.mjs --release` runs the same lock itself, so it cannot be bypassed by calling the CLI directly; `--preview` with `--release` is refused. `web:build:release` also runs `web:release-check` first so that the compile step does not run while the lock holds.

## Decision: public data

Shared assets copy only an allowlist from `apps/web/data/`: `limits.json` and `runtime.json`. Every other data file stays out of the output, including `benchmarks.json` and the `*_source.json` files.

## Decision: shell and slug guards

The page shell fails the build on a `%TOKEN%` with no value or a leftover `{{copy:...}}` directive. The product slug must match `^[a-z0-9][a-z0-9-]*$`, and output cleanup refuses a target outside the output folder.
