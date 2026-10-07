#!/usr/bin/env python3
import json
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import guardlib
from guardlib import Violation

REPLAY = "apps/gateway/replay.json"
LIMITS = "apps/gateway/limits.json"
RULES = "data/replay/replay-rules-v1.json"
PHRASES = "prompts/reply_phrases.json"
TOP_KEYS = frozenset({"status", "turns"})
TURN_KEYS = frozenset({"role", "content"})
ROLES = ("user", "assistant")


@dataclass(frozen=True)
class Rules:
    canary_prefix: str
    secrets: dict[str, re.Pattern[str]]
    email_candidate: re.Pattern[str]
    email_allowed: re.Pattern[str]
    order_number: re.Pattern[str]
    order_min: int
    order_max: int
    max_user_chars: int
    template_examples: frozenset[str]


@dataclass(frozen=True)
class Turn:
    number: int
    role: str
    content: str


def read_object(path: Path) -> dict[str, Any]:
    document: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        message = f"{path.name} must be a JSON object"
        raise TypeError(message)
    return cast(dict[str, Any], document)


def load_rules(root: Path) -> Rules:
    rules = read_object(root / RULES)
    limits = read_object(root / LIMITS)
    examples = cast(dict[str, str], read_object(root / PHRASES)["ask_examples"])
    return Rules(
        canary_prefix=rules["canary_prefix"],
        secrets={name: re.compile(text) for name, text in rules["secret_patterns"].items()},
        email_candidate=re.compile(rules["email_candidate"]),
        email_allowed=re.compile(rules["email_allowed"]),
        order_number=re.compile(rules["order_number"]),
        order_min=rules["order_min"],
        order_max=rules["order_max"],
        max_user_chars=limits["maxMessageChars"],
        template_examples=frozenset(examples.values()),
    )


def fail(reason: str) -> Violation:
    return Violation(REPLAY, 1, reason)


def parse_turn(number: int, raw: object) -> Turn | Violation:
    if not isinstance(raw, dict) or frozenset(cast(dict[str, Any], raw)) != TURN_KEYS:
        return fail(f"turn {number}: must be an object with exactly role and content")
    row = cast(dict[str, Any], raw)
    if row["role"] not in ROLES:
        return fail(f"turn {number}: role must be user or assistant")
    content = row["content"]
    if not isinstance(content, str) or not content.strip():
        return fail(f"turn {number}: content must be a non-empty string")
    return Turn(number, row["role"], content)


def parse_document(document: object) -> tuple[list[Turn], list[Violation]]:
    if not isinstance(document, dict) or frozenset(cast(dict[str, Any], document)) != TOP_KEYS:
        return [], [fail("top level must have exactly the keys status and turns")]
    top = cast(dict[str, Any], document)
    if not isinstance(top["status"], str) or not isinstance(top["turns"], list):
        return [], [fail("status must be a string and turns a list")]
    parsed = [parse_turn(n, raw) for n, raw in enumerate(cast(list[object], top["turns"]), 1)]
    return (
        [item for item in parsed if isinstance(item, Turn)],
        [item for item in parsed if isinstance(item, Violation)],
    )


def strings_in(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in cast(list[object], value):
            yield from strings_in(item)
    elif isinstance(value, dict):
        for key, item in cast(dict[str, object], value).items():
            yield key
            yield from strings_in(item)


def leaks(text: str, rules: Rules) -> Iterator[str]:
    if rules.canary_prefix in text:
        yield f"contains a canary ({rules.canary_prefix})"
    for name, pattern in rules.secrets.items():
        if pattern.search(text):
            yield f"contains a secret shaped like {name}"


def turn_problems(turn: Turn, rules: Rules) -> Iterator[str]:
    if turn.role == "user" and len(turn.content) > rules.max_user_chars:
        yield f"user text is {len(turn.content)} characters, over {rules.max_user_chars}"
    exempt = rules.template_examples if turn.role == "assistant" else frozenset[str]()
    for match in rules.email_candidate.finditer(turn.content):
        if match.group() not in exempt and not rules.email_allowed.fullmatch(match.group()):
            yield "email outside the demo format"
    for match in rules.order_number.finditer(turn.content):
        number = int(match.group(1))
        if match.group() not in exempt and not rules.order_min <= number <= rules.order_max:
            yield f"order {match.group()} is outside #{rules.order_min}-#{rules.order_max}"


def content_violations(
    text: str, document: object, turns: list[Turn], rules: Rules
) -> list[Violation]:
    found = [
        fail(reason) for chunk in (text, *strings_in(document)) for reason in leaks(chunk, rules)
    ]
    for turn in turns:
        found.extend(fail(f"turn {turn.number}: {reason}") for reason in turn_problems(turn, rules))
    return found


def violations(root: Path) -> list[Violation]:
    path = root / REPLAY
    if not path.is_file():
        return [fail("file is missing")]
    try:
        rules = load_rules(root)
        text = path.read_text(encoding="utf-8")
        document: object = json.loads(text)
    except (OSError, ValueError, KeyError, TypeError, re.error) as error:
        return [fail(f"cannot check: {error}")]
    turns, problems = parse_document(document)
    return problems + content_violations(text, document, turns, rules)


def main(argv: Sequence[str] | None = None) -> int:
    root = guardlib.parse_root("Fail when the pre-recorded replay is not safe to publish.", argv)
    return guardlib.report(violations(root))


if __name__ == "__main__":
    sys.exit(main())
