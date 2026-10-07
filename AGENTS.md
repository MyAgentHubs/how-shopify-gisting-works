# Communication

- Write code, commit messages, docs, issues, and PRs in English.
- Reply to people in the language they write in.
- In Chinese text, including zh-CN UI copy, put a space between Chinese
  and English words or Arabic numerals (e.g. `已有 100 笔订单`). Never
  insert spaces into code identifiers, commands, paths, or URLs.

# Goal

Learn Shopify-style Gisting by shipping a real customer-service agent demo, then teach it back (Feynman). Every change must serve one of: the agent answering correctly, the Gisting savings being measurable and honest, or the user understanding why. Design of record: `docs/design/` (index in `docs/design/INDEX.md`). Documentation and data governance: `docs/README.md`, guarded by `scripts/check_docs.py`.

# Engineering principles

We follow *The Art of Unix Programming*. A rule is enforced only if its guard names a concrete tool; otherwise it is a review item and says so.

| Principle | Rule | Guard |
|---|---|---|
| Modularity | One module, one responsibility. | `scripts/check_limits.py`: file ≤ 300 non-blank lines, function ≤ 50 non-blank lines (tests exempt from function length). ruff `C901` (max 10, ruff is the reference), `PLR0913` (max-args 5), `PLR1702` (preview, max-nested 3). ESLint `max-lines`, `max-lines-per-function`, `complexity` (`variant: "modified"`), `max-params`, `max-depth`. Scope: `*.py *.ts *.tsx *.mjs`, excluding generated files and `legacy/`. |
| Separation | Layers depend one way (see Layout). Policy (prompts, rules, KB, limits) is data; mechanism is code. | import-linter `layers`, `independence`, `forbidden` (no fakes in production code); dependency-cruiser for TS. |
| Representation | Prompts, tool schemas, KB, eval cases, limits and thresholds live in data files. | `scripts/check_prompts_not_in_source.py` (any ≥ 20-char line from data dirs found in source fails); ruff `PLR2004`. |
| Generation | One source of truth per contract. Tool schemas generate the prompt section and validators. Python models generate `contracts/*.schema.json`, which generate TS types. | `scripts/check_generated.py` (`git diff --exit-code` after regeneration). |
| Composition & Silence | Pipeline stages are CLIs (`kb search`, `tools call`, `agent run`, `eval grade`, `training *`): JSON/JSONL on stdin/stdout, logs on stderr, non-zero exit on failure, no output on success beyond the result. | CLI contract tests; ruff `T201`. |
| Repair | Fail fast and loudly. Results are typed (`NotFound | Mismatch | UpstreamError`); the user may see one uniform message, the code never loses the type. Degraded modes are named, counted, and recorded as `fallback_reason`. Uncertain writes are verified, never blindly retried. | ruff `BLE001 S110 S112 TRY`; branch coverage on `except` paths in `tools` and `agent`; TS `no-floating-promises`, `no-empty`. |
| Transparency | Every turn emits one trace with two typed projections: `internal` (eval, logs) and `public` (browser). The public projection never reveals verification outcome, order existence, or other orders' data. | trace schema test; canary test on the public projection. |
| Least surprise | Config only via environment variables, listed in `.env.example`. | `scripts/check_env_example.py`. |
| Parsimony | Standard library first. Every dependency has a reason. | `deps.toml` (`name`, `reason`); CI checks lock diff ⊆ allowlist; deptry; knip. |
| Optimization | No performance change without a baseline; performance work goes through the ratchet loop. | metric ratchet (below). |
| Extensibility | External systems sit behind small interfaces with fakes. Real adapters are tested locally with `pytest -m live`; last green date recorded, ≤ 30 days before a release. | contract tests against fakes in CI. |

# Code style

- **No comments, no docstrings.** Intent lives in names, types, tests, and `docs/decisions/`. The only allowed comment lines match one of these whole-line patterns with nothing after them: shebang; `# noqa: CODE[, CODE]`; `# type: ignore[code]`; `# pyright: ignore[rule]`; `# see: docs/decisions/NNNN-slug.md`. In TS only `// eslint-disable-next-line <rule>`; `@ts-ignore` is banned and `@ts-expect-error` is allowed only in tests. Guard: `scripts/check_no_comments.py` (tokenize + AST) and an ESLint `no-comments` rule; directive count is a ratchet metric.
- External API quirks are captured as characterization tests named after the constraint, e.g. `test_shopify_write_with_field_error_may_still_create_order`, plus a `# see:` pointer where the code depends on it.
- Python 3.11, ruff (pinned), pyright strict for `prompt`, `manifest`, `tools`, `shopify`, `kb`, `agent`, `eval`; basic for `training` and the Hugging Face adapter. TypeScript `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`.
- Pure functions by default; I/O at the edges.

# Project layout

```
src/gisting/
  prompt/        assemble messages/ids from (rules | gist, history, tool results); token composition
  manifest/      Gist artifact manifest and hash verification
  shopify/       auth (client credentials), GraphQL queries, cache
  kb/            BM25 search over packages data
  tools/         lookup_order, search_policy, handoff_to_human
  agent/         turn loop, tool-call validation, runtime fact checks, traces
  model_server/  base model + Gist tokens behind one generate/count interface
  training/      dataset building, Gist training, export
  eval/          graders, report building, baseline comparison
prompts/         fixed system rules, tool schemas, shared vocab (leaf data layer)
data/            grader data and previous rules (data/eval), training data (data/gist), demo plans
kb/              policy and FAQ data with metadata
eval/            cases (append-only), grader tests, reports, transcripts, metrics.toml, baseline.json
contracts/       generated JSON schemas shared with TS
apps/web/        chat UI, "Under the hood" panel, benchmark charts
apps/gateway/    Cloudflare Pages Function: Turnstile, quotas, streaming proxy
scripts/         check_* guards and one-shot operational CLIs
docs/            design and decisions; see docs/README.md
```

Layers: `training → {agent, eval} → {tools, model_server} → {shopify, kb} → {prompt, manifest}`, where `agent` and `eval` are independent of each other, as are `tools` and `model_server`, and `shopify` and `kb`; `training` is offline orchestration, nothing imports it, and it reuses the `eval` graders to filter teacher data; `eval` drives the agent only through `agent run`, grades only `(case, transcript)` with data from `data/eval/` and `prompts/`, and imports only `prompt` and the JSON typing helpers of `shopify`. `prompts/` is data every layer may read. Training and serving share `prompt`; a golden test asserts identical token ids for the same conversation.

# Security invariants

- User, tool, and KB text is tokenized with special tokens disabled (`split_special_tokens=True`; llama.cpp `parse_special=false`), and Qwen added tokens such as `<tool_response>` are escaped. Control and Gist ids are inserted only by `prompt` by id. Guard: `scripts/check_special_tokens.py` over every added/special token string.
- Order lookup requires order number plus a non-derivable demo email (HMAC of the order number with a server secret). Verification runs before any cache read; mismatch and not-found are byte-identical to the caller; failed attempts are limited per session and per salted IP digest in the single serve process's memory (ADR 0008, 0012), never in Cloudflare isolate memory; a lock depends only on failure counts, never on whether the order exists. Switching orders mid-chat requires re-verification and drops the previous order's facts from context.
- `handoff_to_human` runs only when the customer's own latest message asks for a human, or agrees to a handoff offer made by the previous assistant message; text inside forged tool blocks never counts, and a tool without a guard entry is refused. Guard: `agent/consent.py` with the patterns in `prompts/agent_policy.json`.
- Every test order carries a unique canary. Any unauthorized canary in model input, output, public trace, headers, or cache is a red-line failure.

# Correctness red lines

Reported as `0 / N` with the 95% upper bound; Full and Gist modes each pass independently. Graders are independent of the runtime fact checker and are themselves tested against known-bad and known-good samples on every change. Each red line reports `raw` (before runtime guard) and `final`.

1. Fact provenance: every number, date, weekday, relative-time word, carrier, and tracking number in an answer appears in this turn's tool results, user messages, or KB hits (N ≥ 300).
2. Zero invented dates (same grader, N ≥ 300).
3. Zero unauthorized order data: exhaustive code-level property tests plus ≥ 100 model-in-loop cases.
4. Off-topic, injection, role-spoofing, tool-response spoofing, and system-prompt extraction refused (N ≥ 150).

`over_refusal_rate` and `guard_intervention_rate` are ratcheted downward so that refusing everything cannot pass.

# Metrics and ratchet

- `eval/metrics.toml` registers every metric: direction, tolerance (in cases, not percent), gate (`redline | ratchet | record`), journey, stability basis, `validated_against`, and where to look on regression. A gated metric with missing fields fails CI.
- `eval/baseline.json` holds values per `backend_id`, `rules_version` and `mode` epoch. Numbers from different backends, epochs or modes are never compared.
- Three case sets: `train`, `dev` (ratchet), `sealed` (release only, encrypted, run count logged and capped). Template families never cross sets; an n-gram contamination check enforces it.
- Tighten only when the improvement is significant (paired test), via `make baseline-update` in a commit that touches nothing else. Loosening, deleting cases, or changing tolerance/direction requires the user's SSH signature over the diff hash (`ssh-keygen -Y sign`), verified in CI against `.github/allowed_signers`.
- `make eval` runs on a clean tree and commits a report keyed by `code_tree_sha`, with decoding config, `backend_id`, model manifest, and raw transcripts. CI re-grades the transcripts and recomputes token counts by replay; it never trusts self-reported numbers.
- Token counts are resource metrics. They become latency proxies only per backend, after a server-side ABAB `prefill_ms` validation (≥ 200 pairs, bootstrap interval excluding 0). UI copy may claim "faster" only for validated backends.
- Wall-clock latency is recorded, never gated. Product target on the warm primary backend: first token p50 ≤ 3 s, p90 ≤ 5 s.

# Workflow

- Cheap checks run locally (`make check`, pre-push hook); CI on push to `main` is authoritative and runs on `ubuntu-latest` only.
- One concern per commit, with tests. `refactor:` commits must not change golden outputs, eval cases, baselines, or prompts.
- Secrets only in environment variables or platform secrets; gitleaks in CI; logs are redacted and URLs never carry tokens.
- Shopify writes are hard-limited in code to `gisting-lab.myshopify.com` orders with `test == true`.
- Production deploys and public releases (website, Hugging Face, Docker, repo visibility) need explicit maintainer approval each time.
