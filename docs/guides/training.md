---
type: guide
status: current
updated: 2026-10-07
summary: Context distillation trains only gist vectors on recorded teacher responses.
---

# Training the gist vectors

[English](training.md) | [简体中文](training.zh-CN.md)

Full teacher and Gist student are **the same frozen Qwen3-1.7B model**.
The teacher sees expanded rules; the student sees 16 learned input vectors in
that segment. Tool schemas and conversation context remain present in both.
This is context distillation as a training objective, not a smaller replacement
model. Only the gist tensor is optimized.

## What is actually minimized

[`run_training()`](../../src/gisting/training/gist_run.py) disables gradients on
all network parameters and hashes them before and after training. A changed hash
raises an error. [`AdamW`](../../src/gisting/training/trainer.py) receives only
`[run.gist]`, with zero weight decay; gradient clipping likewise targets gist.

For each retained teacher record, both views consume the **same recorded response
IDs** as a teacher-forced continuation. The teacher distribution is recomputed
without gradients. The student distribution uses injected gist embeddings.
[`kl_per_token()`](../../src/gisting/training/forward.py) computes
`KL(P_teacher || P_student)` over the full vocabulary, then training averages
across selected response positions and across examples in the batch.

[`make_example()`](../../src/gisting/training/examples.py) selects next-token
prediction positions from `prefix_length - 1` through
`prefix_length + target_length - 2`, separately offset for each prefix.
It covers **every recorded response token**, including wording and tool-call
syntax/arguments. [`target_ids()`](../../src/gisting/training/teacher.py) appends
the message-end ID when generation finished with `stop`, so that stop prediction
is trained too. Prefix positions are not loss targets. Overlength examples are
skipped when Full prefix + target exceeds the configured maximum.

The filtering/measurement layer is a separate choice: `filter` CLI defaults to
`decision` (action and facts), while the underlying filtering function defaults
to `raw`. `read_teacher()` re-grades at `raw` by default, but example construction
does not use that verdict to discard rows or mask token positions. Consequently,
decision-only filtering does **not** make KL decision-only. The implementation
has no semantic mask selecting only decision/fact tokens.

## Data, recording, filtering, and audit

[`build_dataset()`](../../src/gisting/training/dataset.py) draws reproducible
synthetic samples using seeded templates, categories, split families, and order
pools from [`data/gist/`](../../data/gist/templates.json) and the synthetic plan.
Samples include first-call decisions and multi-turn/tool-result contexts.

`teach` records Full-mode response IDs/text, finish reason, token counts,
timing, backend identity, and grader verdict. Recording is resumable by sample
ID; use a fresh output file for a new teacher/configuration rather than mixing
runs. `filter` deterministically re-grades records and retains passing rows,
reporting per-split/category totals, rejections, and empty groups. Choose the
layer explicitly when reproducing an experiment.

Manually inspect a sample of retained and rejected rows across categories and
splits before accepting training data. Check action arguments, grounded facts,
refusals, missing inputs, and consent; record the sample selection and findings.
This is a review step, **not an automated gate implemented by these CLIs**.
Empty-group reporting also does not itself block training. Lower KL alone does
not establish runtime correctness or a passed release evaluation.

## Opt-in pipeline commands

These commands generate teacher responses and train a model input artifact.
First follow [usage prerequisites](using-gist-tokens.md): Python 3.11,
`uv sync --extra model`, the pinned local base model with tokenizer and checksum
metadata, and `GISTING_MODEL_DIR` set to its directory. `GISTING_DEVICE` is optional.
These training commands use constructed synthetic samples and recorded contexts;
they do not call the live Shopify API or require live demo credentials.

```sh
mkdir -p artifacts/tutorial
uv run python -m gisting.training build --out artifacts/tutorial/dataset.jsonl
uv run python -m gisting.training teach --dataset artifacts/tutorial/dataset.jsonl --out artifacts/tutorial/teacher.jsonl
uv run python -m gisting.training filter --teacher artifacts/tutorial/teacher.jsonl --layer decision --out artifacts/tutorial/train_set.jsonl
uv run python -m gisting.training gist --teacher artifacts/tutorial/train_set.jsonl --run-id example-run --out-dir artifacts/gist
uv run python -m gisting.training compare --teacher artifacts/tutorial/train_set.jsonl --gist-dir artifacts/gist/example-run --out artifacts/tutorial/compare.json
```

`build` writes stdout when `--out` is omitted. `teach` reads stdin when `--dataset`
is omitted and supports `--limit`; `--out` is required and appended resumably.
`filter` supports `decision`, `raw`, and `final`. Neither a small `--limit` trial
nor an empty/imbalanced filtered partition is enough for a meaningful training run.

[`data/gist/hparams.json`](../../data/gist/hparams.json) sets k = 16,
seed = 20261002, learning rate = 0.005, epochs = 6, batch size = 4,
max length = 2560, gradient clip = 1.0, chunk-mean initialization, and gradient
checkpointing. Chunk-mean initialization derives vectors from the Full rules'
embedding chunks; random initialization is also supported by the implementation.
Configuration lives in data, not extra undocumented CLI flags.

## Outputs and comparison scope

`gist` writes `artifacts/gist/<run-id>/gist.safetensors`, `manifest.json`,
`training-log.jsonl`, and `summary.json`. Existing artifact filenames cause
rejection; choose a new run ID. The float32 `gist` tensor is 16 × 2048 for this
configuration. The [manifest](../../src/gisting/training/artifact.py) binds base
revision/checksum metadata, rules/tools hashes, dimensions, placeholder ID,
backend, teacher-file hash, hyperparameter hash, and gist checksum. The summary
records before/after base parameter hashes, unchanged status, dataset counts,
overlength skips, and KL progress.

`compare` validates provenance and runs Full, untrained Gist, and trained Gist
on the supplied teacher dataset's **dev partition only**, graded at `decision`.
It writes a comparison report and sample outputs. It is not the independent
full agent evaluation of 933 train/dev cases linked from the README; it does not
exercise the whole serve/gateway/runtime path. Training-source example files
under `artifacts/` are not exported as public evidence. Recreate them with
`build` and `teach` when needed.

Rule or tool changes need fresh matched artifacts and evaluation in a new epoch;
keep frozen prompts, cases, and baselines intact during reproduction.

[Fixed-rules boundary](fixed-rules.md) | [Architecture](architecture.md)
