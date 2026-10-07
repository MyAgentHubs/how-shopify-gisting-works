#!/usr/bin/env python3
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import guardlib
from guardlib import Violation
from schema_to_ts import render_types

from gisting.agent.public_trace import PublicTrace
from gisting.eval.case_spec import EvalCase
from gisting.eval.dataclass_json import json_schema
from gisting.eval.web_benchmarks import Benchmarks
from gisting.eval.web_pricing import Pricing
from gisting.prompt.public_rules import PublicRules, render_public_rules
from gisting.serve.contract import ServeContract


def render(cls: type) -> str:
    return json.dumps(json_schema(cls), indent=2) + "\n"


GENERATED: dict[str, Callable[[], str]] = {
    "contracts/eval_case.schema.json": lambda: render(EvalCase),
    "contracts/eval_case.generated.ts": lambda: render_types(json_schema(EvalCase)),
    "contracts/benchmarks.schema.json": lambda: render(Benchmarks),
    "contracts/benchmarks.generated.ts": lambda: render_types(json_schema(Benchmarks)),
    "contracts/pricing.schema.json": lambda: render(Pricing),
    "contracts/pricing.generated.ts": lambda: render_types(json_schema(Pricing)),
    "contracts/public_trace.schema.json": lambda: render(PublicTrace),
    "contracts/public_trace.generated.ts": lambda: render_types(json_schema(PublicTrace)),
    "contracts/public_rules.schema.json": lambda: render(PublicRules),
    "contracts/public_rules.generated.ts": lambda: render_types(json_schema(PublicRules)),
    "apps/web/data/public_rules.json": render_public_rules,
    "contracts/serve.schema.json": lambda: render(ServeContract),
    "contracts/serve.generated.ts": lambda: render_types(json_schema(ServeContract)),
}


def stale(root: Path) -> list[Violation]:
    found: list[Violation] = []
    for relative, generate in GENERATED.items():
        target = root / relative
        if not target.is_file():
            found.append(Violation(relative, 1, "file is missing"))
        elif target.read_text(encoding="utf-8") != generate():
            found.append(Violation(relative, 1, "differs from the generated output"))
    return found


def write(root: Path) -> None:
    for relative, generate in GENERATED.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generate(), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = guardlib.make_parser("Fail when a generated contract differs from its source model.")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.write:
        write(root)
    return guardlib.report(stale(root))


if __name__ == "__main__":
    sys.exit(main())
