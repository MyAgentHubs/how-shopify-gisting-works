#!/usr/bin/env python3
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path

import guardlib
from guardlib import Violation

from gisting.eval.case_files import LoadedCase, load_cases
from gisting.eval.contamination import (
    Hit,
    Policy,
    Text,
    contaminated,
    load_policy,
    tokens_of,
    training_family_names,
    training_texts,
)

POLICY_FILE = "data/eval/contamination-v1.json"
TEMPLATES_FILE = "data/gist/templates.json"


def family_violations(cases: list[LoadedCase], training_names: frozenset[str]) -> list[Violation]:
    splits: dict[str, set[str]] = defaultdict(set)
    for item in cases:
        splits[item.case.family].add(item.case.split)
    found: list[Violation] = []
    for item in cases:
        family = item.case.family
        if len(splits[family]) > 1:
            where = ", ".join(sorted(splits[family]))
            reason = f"family {family} is used in more than one split: {where}"
            found.append(Violation(item.path, item.line, reason))
        if family in training_names:
            found.append(
                Violation(item.path, item.line, f"family {family} is also a training family")
            )
    return found


def hit_violations(hits: list[Hit], origins: dict[str, LoadedCase]) -> list[Violation]:
    return [
        Violation(
            origins[hit.candidate].path,
            origins[hit.candidate].line,
            f"{hit.candidate} shares {hit.shared} n-grams with {hit.reference}",
        )
        for hit in hits
    ]


def texts_by_split(cases: list[LoadedCase], policy: Policy) -> dict[str, list[Text]]:
    by_split: dict[str, list[Text]] = defaultdict(list)
    for item in cases:
        for message in item.case.messages:
            if message.role == "user":
                by_split[item.case.split].append(
                    Text(item.case.id, tokens_of(message.content, policy))
                )
    return by_split


def contamination_violations(
    cases: list[LoadedCase], policy: Policy, training: list[Text]
) -> list[Violation]:
    by_split = texts_by_split(cases, policy)
    hits: list[Hit] = []
    for left, right in combinations(sorted(by_split), 2):
        hits += contaminated(by_split[left], by_split[right], policy)
        hits += contaminated(by_split[right], by_split[left], policy)
    hits += contaminated([text for texts in by_split.values() for text in texts], training, policy)
    return hit_violations(hits, {item.case.id: item for item in cases})


def check(root: Path) -> list[Violation]:
    try:
        policy = load_policy(root / POLICY_FILE)
        document = json.loads((root / TEMPLATES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        missing = POLICY_FILE if not (root / POLICY_FILE).is_file() else TEMPLATES_FILE
        return [Violation(missing, 1, f"cannot load: {error}")]
    cases, _ = load_cases(root)
    return [
        *family_violations(cases, training_family_names(document)),
        *contamination_violations(cases, policy, training_texts(document, policy)),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    root = guardlib.parse_root("Fail when eval sets share families or text with each other.", argv)
    return guardlib.report(check(root))


if __name__ == "__main__":
    sys.exit(main())
