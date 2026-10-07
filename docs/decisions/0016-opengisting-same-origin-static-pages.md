---
type: decision
status: current
updated: 2026-10-06
superseded_in_part_by: docs/decisions/0018-release-lock-and-public-data-as-built.md
summary: The OpenGisting product page ships as one static file per language inside the www Pages project, same origin as the gateway function (no CORS, no page-owned top bar); hreflang covers only indexed languages; the session meter is computed in the browser; the calculator is a labelled what-if; Turnstile is checked for hostname and action; price freshness is checked only by the release lock
---

# 0016: OpenGisting as same-origin static pages

Status: accepted (2026-10-06, user-approved design, review page and lead rulings of the same day). Nothing earlier is reversed: the gateway counters (0006) and the serve process (0008, 0012, 0013) are unchanged.

## Context

The page was one template that picked a language at runtime and fetched its copy and a benchmarks file. The product now lives under the www site, which already owns the top bar, the language menu, the footer brand and the Pages project that serves `/api/chat`.

## Decision: hosting and build

- **Same origin.** Pages sit in the www Pages project under `site/opengisting/`. The gateway is that project's `functions/api/chat.ts`, path `/api/chat`. There is no gateway URL in the page and no CORS handling.
- **One file per language, no page-owned top bar.** `/opengisting/`, `/zh-CN/opengisting/`, `/ja/opengisting/`, `/ko/opengisting/`. `<html lang>` matches the path; there is no `?lang=`, no navigator negotiation, no in-page language switch. Shared assets live once under `/opengisting/`. The footer keeps a `a.mh-footer-brand` slot for www to fill.
- **Product constants are data** (`apps/web/product.json`): name, slug, origin, and per language `code`, `htmlLang`, `hreflang`, `prefix`, `indexed`.
- **ja and ko** show the English body plus one line saying that language is in preparation. Native review of that line is pending with the user.
- **Public data.** `apps/web/data/` is copied as a directory, except `*_source.json` and `benchmarks*.json`. The page never fetches `benchmarks.json`; build inlines only the few numbers it needs. No accuracy comparison appears anywhere public.

## Decision: hreflang and indexing

- `en` and `zh-CN` pages: self canonical, hreflang `en`, `zh-Hans`, `x-default` (to en), in the sitemap.
- `ja` and `ko` pages: self canonical, no hreflang, `noindex`, not in the sitemap.
- The set comes from `indexed` in `product.json`, not from code.

## Decision: numbers shown to visitors

- **Session meter in the browser.** Only Gist replies count. `calls = rules tokens / 19` must be an integer, else the turn is skipped. Each call saves 507 (526 minus 19); `fullWould = gistUsed + calls * 507`. Compare turns, recorded replays and failed replies are excluded. Nothing is sent or stored. No `PublicTokens` field is added.
- **Calculator is a what-if.** It runs in the browser from `benchmarks.json` derived values and `pricing.json`, is labelled as an assumed scenario, and a model whose minimum cacheable prefix exceeds the prefix prices both views the same. Data keeps 493.4 saved tokens per turn (507 * 908 / 933); the page shows 493.
- **Price freshness** (45 days) is checked only by the release lock, never by `make check`, so CI does not turn red with time.

## Decision: Turnstile

The gateway adds two checks on a successful siteverify answer: `hostname` is in an allowed set from data, and `action` equals the expected one. A missing value is a rejection. The caller sees the same response as any other failure; the code keeps typed internal reasons `hostname_mismatch` and `action_mismatch`. Siteverify still receives only the secret and the token, never the visitor IP. An optional environment variable may add hostnames in the Pages preview environment only. The widget script loads lazily (first input focus or example click), appearance `interaction-only`.

## Release lock

A build is marked draft, and the release build exits non-zero without writing output, while any of these holds: Cloudflare test sitekey, placeholder example email, price data older than 45 days, a copy file not `approved`, or the research write-up link still a placeholder.
