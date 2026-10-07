# Documentation and data governance

Enforced by `scripts/check_docs.py` (part of `make check`). The docs root uses this file as its index. Start with the [public guides](guides/INDEX.md) for architecture, Gist tokens, fixed rules and training.

## Document types

| type | location | how it changes | line cap | when stale |
|---|---|---|---|---|
| decision | `docs/decisions/NNNN-slug.md` | immutable; a reversal is a new file and the old one gets `superseded_by` | 60 | kept |
| design | `docs/design/<topic>.md`, one per topic | edited in place, history is git | 400, split by topic when exceeded | delete the old version |
| guide | `docs/guides/<topic>.md`, one per public topic | edited in place, history is git | 200 | update with the current behavior |
| run | `docs/learning/runs/<date>-<run-id>.md` | immutable | 150 | kept, browse via the index |
| concept | `docs/learning/concepts/<concept>.md`, one per concept | rewritten when the understanding changes, never appended | 150 | overwritten |
| handoff | `docs/handoff.md`, only the latest | overwritten whole each time | 300 | overwritten |

## Rules

- Every docs directory has an `INDEX.md` with one line per file; the guard fails on unlisted files and on entries pointing to missing files.
- Every document starts with front matter: `type`, `status` (`current` or `superseded`), `updated` (`YYYY-MM-DD`), `summary` (one-sentence conclusion). `type` must match the directory. A `superseded` document needs `superseded_by`, a repo-root-relative path to an existing file. `README.md` and `INDEX.md` files have no front matter.
- A decision that is reversed only in part stays `current` and names the newer decision in `superseded_in_part_by`; the body says which part.
- The docs root holds only `README.md` and `handoff.md`.
- No bulk raw data in the body. Raw data lives in `artifacts/<area>/<run-id>/`; the body cites the path and its sha256.
- No generated HTML under `docs/`. Generated HTML is kept outside this documentation tree.
- Do one tidy-up pass at the end of every milestone.

## Data

| class | location | tracked | rule |
|---|---|---|---|
| source data | `data/`, `prompts/`, `kb/`, `eval/cases/` | yes | version number in the file name; `eval/cases` is append-only |
| run artifacts | `artifacts/<area>/<run-id>/` | no | carries a manifest; anything referenced by a baseline or report is kept forever, otherwise keep the latest 5 runs per area and clean up by hand before the 6th (write a cleanup script when needed) |
| eval reports | `eval/reports/<code_tree_sha>/` | yes | commit only the summary `report.json`; transcripts as plain `.jsonl`; a run over 5 MB goes to artifacts with its sha256 recorded |
