RUN := uv run --frozen
EVAL_ARGS ?= --split dev
RATCHET_BASE ?= $(shell git merge-base --is-ancestor origin/main HEAD 2>/dev/null && git rev-parse origin/main)
SHELL_FILES := $(wildcard scripts/*.sh scripts/tests/*.sh .githooks/*)

.PHONY: check check-ts eval baseline-update guard-hash guard-genesis web-preview

check:
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(RUN) pyright
	@for guard in $(filter-out scripts/check_eval_ratchet.py,$(wildcard scripts/check_*.py)); do $(RUN) python "$$guard" || exit 1; done

	$(RUN) pytest -q
	@for suite in scripts/tests/*.sh; do bash "$$suite" || exit 1; done
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck $(SHELL_FILES); else echo "shellcheck not installed, skipped" >&2; fi
	@if command -v gitleaks >/dev/null 2>&1; then gitleaks git --no-banner; else echo "gitleaks not installed, skipped" >&2; fi
	uv lock --check
	$(RUN) deptry .
	$(RUN) lint-imports
	$(MAKE) check-ts

check-ts:
	pnpm install --frozen-lockfile
	pnpm run typecheck
	pnpm run lint
	pnpm run depcruise
	pnpm run knip
	pnpm run test

eval:
	$(RUN) --extra model python -m gisting.eval evaluate $(EVAL_ARGS)

baseline-update:
	$(RUN) python -m gisting.eval baseline-update $(BASELINE_ARGS)

guard-hash:
	$(RUN) python -m gisting.eval guard-hash $(GUARD_ARGS)

guard-genesis:
	$(RUN) python -m gisting.eval guard-hash --genesis $(GUARD_ARGS)

web-preview:
	pnpm run web:build:preview
	python3 -m http.server 4173 --bind 127.0.0.1 --directory dist/web

