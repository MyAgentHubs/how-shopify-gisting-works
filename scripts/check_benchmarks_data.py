#!/usr/bin/env python3
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

import guardlib
from guardlib import Violation

from gisting.eval.web_benchmarks import build_benchmarks
from gisting.shopify.jsonvalue import Json, JsonObject, MalformedResponse

SOURCE = "apps/web/data/benchmarks_source.json"
OUTPUT = "apps/web/data/benchmarks.json"
REPORTS = "eval/reports"
REPORT_FILE = "report.json"
TRANSCRIPTS_FILE = "transcripts.jsonl"
MODES = ("full", "gist")


def read_object(path: Path) -> JsonObject:
    document: Json = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise MalformedResponse(path.name)
    return document


def read_transcripts(path: Path) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row: Json = json.loads(line)
        if not isinstance(row, dict):
            raise MalformedResponse(path.name)
        rows.append(row)
    return rows


def render(root: Path) -> str:
    tree = read_object(root / SOURCE).get("code_tree_sha")
    if not isinstance(tree, str):
        raise MalformedResponse("code_tree_sha")
    full, gist = (read_object(root / REPORTS / tree / mode / REPORT_FILE) for mode in MODES)
    transcripts = read_transcripts(root / REPORTS / tree / "gist" / TRANSCRIPTS_FILE)
    return json.dumps(asdict(build_benchmarks(full, gist, transcripts)), indent=2) + "\n"


def stale(root: Path) -> list[Violation]:
    try:
        expected = render(root)
    except (OSError, ValueError) as error:
        return [Violation(SOURCE, 1, f"cannot build the benchmarks data: {error}")]
    target = root / OUTPUT
    if not target.is_file():
        return [Violation(OUTPUT, 1, "file is missing")]
    if target.read_text(encoding="utf-8") != expected:
        return [Violation(OUTPUT, 1, "differs from the committed eval reports")]
    return []


def main(argv: Sequence[str] | None = None) -> int:
    parser = guardlib.make_parser(
        "Fail when the web benchmarks data differs from the eval reports."
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.write:
        (root / OUTPUT).write_text(render(root), encoding="utf-8")
    return guardlib.report(stale(root))


if __name__ == "__main__":
    sys.exit(main())
