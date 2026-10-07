---
type: decision
status: current
updated: 2026-10-06
summary: Extra Turnstile hostnames are a preview-only setting that production must leave empty, preview aliases are listed by exact name, how Cloudflare's test keys behave in siteverify is left open until a live preview, and the page build carries a draft marker and an output check that a release must pass
---

# 0017: Turnstile preview hostnames and page build gates

Status: accepted (2026-10-06, lead rulings 16 and 23 and the final acceptance of the page). Extends 0016 (its Turnstile and release lock sections); nothing in 0016 is reversed.

## Context

0016 said an optional environment variable may add hostnames in the Pages preview environment only. The review of the gateway change asked for the rules around it to be written down. The page build also gained gates after 0016 that belong beside its release lock.

## Decision: Turnstile hostnames

- The allowed hostnames are `hostnames` in `apps/gateway/turnstile.json` plus the comma-separated `GISTING_TURNSTILE_EXTRA_HOSTNAMES`. The expected `action` is `action` in the same file.
- **Preview only.** The variable is set in the Pages preview environment and nowhere else. **Production leaves it empty**, because every extra name lets a widget on that host mint tokens this gateway accepts.
- **Exact names.** A preview alias is listed by its full hostname. Wildcards are not accepted; a malformed entry makes the gateway configuration check fail instead of being skipped.
- **Action pair.** The page reads the sitekey and action from `data/runtime.json`. The gateway test that ties `turnstile.json` to `runtime.json` stays in product CI. The www import must also assert that the rendered widget's `data-action` equals that action.
- **Open.** Whether Cloudflare's published test sitekey and secret return a hostname and action that pass these checks in siteverify is not known. It is verified in the first live preview. This decision does not relax either check for a test key.

## Decision: page build gates

- Every build except `web:build:release` writes `<meta name="build-state" content="draft">`. The release build runs the release lock first, exits non-zero without writing output while the lock holds, and omits the marker. The marker is a meta tag only; no visible banner is required.
- `web:verify` (`apps/web/scripts/verify-output.mjs`, limits in `verify-rules.json`) checks a build: one page per language with matching `<html lang>`, self canonical, hreflang only for indexed languages plus `x-default`, `noindex` on the rest, an `og:image` file that exists, one `h1`, and at most 750 default-visible English words counted the way the review page counted (738 at the time of writing).
- It scans every published file for the benchmarks data and red lines, private policy and word-list file names, hardware or hosting details, speed claims (the one negating disclaimer is the only exception), the www header chrome and `.hero .eyebrow`. It also rejects a published copy file, and a preview script or fake gateway in a build that does not use them. A release build additionally fails on placeholder copy and on the draft marker.
