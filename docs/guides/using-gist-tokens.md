---
type: guide
status: current
updated: 2026-10-07
summary: Load matched gist artifacts and compare Full and Gist honestly.
---

# Using gist tokens

[English](using-gist-tokens.md) | [简体中文](using-gist-tokens.zh-CN.md)

The configuration of record is **Qwen3-1.7B**, revision
`70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, with hidden size **2048**.
See [model candidates](../../models/candidates.json).
The trained tensor is `gist` in `gist.safetensors`: float32, **16 × 2048**,
or 32,768 learned scalar values. The base model weights are unchanged.
[Gist weights and manifest](https://huggingface.co/ImPanda/how-shopify-gisting-works)
are available on Hugging Face.

## Prerequisites

Use Python 3.11 and uv. Basic checks need the default dependencies; model runtime
and training additionally need the `model` extra (torch, transformers,
safetensors). See [dependency declarations](../../pyproject.toml).
Run commands from the repository root. These opt-in setup commands download
base weights; the download script also needs the `hf` CLI
from `huggingface_hub` (version 0.34 or newer), Bash, and its checksum utilities.

```sh
uv sync --extra model
export GISTING_MODELS_DIR=./models/hf
bash scripts/download-models.sh qwen3-1.7b
export GISTING_MODEL_DIR=./models/hf/qwen3-1.7b
```

The loader uses local files only. Keep tokenizer files, configuration, base
weights, `.revision`, and `SHA256SUMS` together in that model directory.
`GISTING_DEVICE` optionally selects the torch device; omit it for the loader's
default. An artifact must match the runtime's backend ID, including dtype;
changing the device/backend may therefore invalidate an existing artifact.
Use a newly matched artifact rather than bypassing its manifest.

## Download the released gist artifact

The release is run `k16-v8-seed20261002`, with
`backend_id` `transformers-mps-bfloat16`. Download its weights and manifest:

```sh
hf download ImPanda/how-shopify-gisting-works --local-dir ./artifacts/gist/k16-v8
(cd ./artifacts/gist/k16-v8 && shasum -a 256 -c SHA256SUMS)
export GISTING_GIST_DIR=./artifacts/gist/k16-v8
```

Local checksum verification does not replace runtime manifest validation.
The artifact must pass all existing exact manifest checks listed below.
CPU and other backends are not automatically compatible; use an artifact
matched to the runtime rather than bypassing or rewriting the manifest.

## Insertion is by ID, not visible text

[`gist_rules()`](../../src/gisting/prompt/assemble.py) repeats **the same**
placeholder ID `151669` 16 times for this release. The ID is one beyond the
tokenizer's maximum vocabulary ID; it must still fit the model's embedding table. These are 16 positions,
not 16 new visible vocabulary strings. During input embedding,
[`embed_with_gist()`](../../src/gisting/model_server/gist.py) substitutes the
16 learned rows at those positions in order. It does not alter the base embedding
weights. Typing a supposed gist token into a chat does not activate this path.

The [artifact loader](../../src/gisting/model_server/gist_store.py) verifies
manifest fields, gist checksum, float32 shape, and placeholder capacity.
Compatibility checks include base revision and checksum-list hash, expanded
rules hash, tools-ID hash, hidden size, placeholder ID, and backend ID.
The manifest also records dataset and training configuration hashes;
`training compare` checks those against the supplied teacher file/configuration.

[User-text tokenization](../../src/gisting/prompt/tokenizer.py) splits added-token
spellings so they cannot become control IDs. User, tool, and KB content remains
untrusted text; only prompt assembly inserts trusted controls and gist IDs.
This preserves the security boundary when a customer types role/tool markers.

## Offline inspection before runtime

These commands read committed data or show parser help; they do not generate
model output, run evaluation, or train:

```sh
uv run python scripts/check_benchmarks_data.py
uv run python scripts/check_docs.py
uv run python -m gisting.agent --help
uv run python -m gisting.agent run --help
uv run python -m gisting.training --help
```

The [Full report](../../eval/reports/ee6c5c626278120523b9af02255958c0c9f5048c/full/report.json) and
[Gist report](../../eval/reports/ee6c5c626278120523b9af02255958c0c9f5048c/gist/report.json) are the recorded
933-case comparison. Inspect `tokens`, `cases`, `run`, and raw/final metric
layers. The [web composition derivation](../../src/gisting/eval/web_benchmarks.py)
explains the controlled 968 → 461 illustration. See
[fixed rules](fixed-rules.md) for rounding and denominators.

## Opt-in runtime: Full and Gist

The following commands really load a model and generate a reply. They use the
local synthetic transport, not the live Shopify API. Local fixtures under
`data/demo-orders/` must be present. Set a demo-only email secret and explicitly
supply an empty project-relative env file so no default credential file is used.
In Bash, enter a fresh demo-only secret at the silent `read` prompt below.
The example asks about delivery without credentials, so it needs no real order
email. The runtime still constructs its tool dependencies.

```sh
mkdir -p artifacts
: > artifacts/local-runtime.env
read -r -s GISTING_EMAIL_SECRET
export GISTING_EMAIL_SECRET
printf '%s\n' '{"session_id":"local-full","messages":[{"role":"user","content":"Where is my order?"}]}' |
  uv run python -m gisting.agent run --mode full --transport local --env-file artifacts/local-runtime.env
```

For Gist, use the released artifact directory below. If you bring your own
compatible artifact, choose its path instead; the directory must contain
`manifest.json` and `gist.safetensors`:

```sh
export GISTING_GIST_DIR=./artifacts/gist/k16-v8
printf '%s\n' '{"session_id":"local-gist","messages":[{"role":"user","content":"Where is my order?"}]}' |
  uv run python -m gisting.agent run --mode gist --transport local --env-file artifacts/local-runtime.env
```

Both modes accept one JSON request on stdin and emit `answer` plus public `trace`
on stdout. `--internal` adds the internal trace for local inspection;
`--batch` accepts one request per stdin line. A named fallback returns exit 1;
usage/loading errors return exit 2. Default tool transport is HTTP, so retain
`--transport local` for these examples. CLI invocations are separate processes;
use serve for persistent sessions and shared failure limits.

[Architecture](architecture.md) | [Train your own artifact](training.md)
