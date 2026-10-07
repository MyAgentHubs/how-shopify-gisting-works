#!/usr/bin/env python3
import sys
from collections.abc import Sequence
from pathlib import Path

import guardlib
from guardlib import Violation

from gisting.eval.baseline import baseline_problems, load_baseline
from gisting.eval.dataclass_json import DecodeError
from gisting.eval.registry import load_registry

METRICS_FILE = "eval/metrics.toml"
BASELINE_FILE = "eval/baseline.json"


def check(root: Path) -> list[Violation]:
    metrics, problems = load_registry(root / METRICS_FILE)
    found = [Violation(METRICS_FILE, 1, item) for item in problems]
    try:
        baseline = load_baseline(root / BASELINE_FILE)
    except (OSError, ValueError, DecodeError) as error:
        return [*found, Violation(BASELINE_FILE, 1, f"cannot load: {error}")]
    registered = frozenset(metric.name for metric in metrics)
    return [
        *found,
        *(Violation(BASELINE_FILE, 1, item) for item in baseline_problems(baseline, registered)),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    root = guardlib.parse_root("Fail when the metric registry or baseline is incomplete.", argv)
    return guardlib.report(check(root))


if __name__ == "__main__":
    sys.exit(main())
