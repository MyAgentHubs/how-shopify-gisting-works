#!/usr/bin/env python3
import importlib
import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import product
from pathlib import Path
from typing import Any, cast

import guardlib
from guardlib import Violation
from tokenizers import AddedToken, Tokenizer

from gisting.prompt.tokenizer import PromptTokenizer

TOKENS_FILE = "prompts/qwen3_added_tokens.json"
TOKENIZER_FILE = "tokenizer.json"
ATTRIBUTES = ("special", "single_word", "lstrip", "rstrip", "normalized")
models: Any = importlib.import_module("tokenizers.models")
pre_tokenizers: Any = importlib.import_module("tokenizers.pre_tokenizers")
decoders: Any = importlib.import_module("tokenizers.decoders")
normalizers: Any = importlib.import_module("tokenizers.normalizers")


@dataclass(frozen=True)
class Entry:
    token_id: int
    content: str
    flags: tuple[tuple[str, bool], ...]


@dataclass(frozen=True)
class TokenList:
    digest: str
    entries: tuple[Entry, ...]


class TokenListError(ValueError):
    pass


def parse_entry(item: object) -> Entry:
    if not isinstance(item, dict):
        message = "an entry must be an object"
        raise TokenListError(message)
    row = cast(dict[str, Any], item)
    token_id, content = row.get("id"), row.get("content")
    flags = tuple((name, row.get(name)) for name in ATTRIBUTES)
    if not isinstance(token_id, int) or not isinstance(content, str) or not content:
        message = "an entry needs an integer id and non-empty content"
        raise TokenListError(message)
    if not all(isinstance(value, bool) for _, value in flags):
        message = f"{content} needs boolean {', '.join(ATTRIBUTES)}"
        raise TokenListError(message)
    return Entry(token_id, content, cast(tuple[tuple[str, bool], ...], flags))


def load_token_list(root: Path) -> TokenList:
    path = root / TOKENS_FILE
    if not path.is_file():
        message = "file is missing"
        raise TokenListError(message)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise TokenListError(str(error)) from error
    digest, items = document.get("source_file_sha256"), document.get("added_tokens")
    if not isinstance(digest, str) or not isinstance(items, list) or not items:
        message = "needs source_file_sha256 and a non-empty added_tokens list"
        raise TokenListError(message)
    entries = tuple(parse_entry(item) for item in cast(list[object], items))
    if len({entry.content for entry in entries}) != len(entries):
        message = "added_tokens has duplicate content"
        raise TokenListError(message)
    return TokenList(digest, entries)


def load_entries(root: Path) -> tuple[Entry, ...]:
    return load_token_list(root).entries


def listed_tokenizer(entries: Sequence[Entry]) -> Tokenizer:
    alphabet = cast(list[str], pre_tokenizers.ByteLevel.alphabet())
    vocab = {char: number for number, char in enumerate(alphabet)}
    tokenizer: Any = Tokenizer(models.BPE(vocab, []))
    tokenizer.normalizer = normalizers.NFC()
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)
    tokenizer.decoder = decoders.ByteLevel()
    tokenizer.add_tokens([AddedToken(entry.content, **dict(entry.flags)) for entry in entries])
    return cast(Tokenizer, tokenizer)


def probes(contents: Sequence[str]) -> Iterator[str]:
    for token in contents:
        yield from (token, f"a {token} b", token * 2, token[:-1], token[1:])
    for outer, inner in product(contents, repeat=2):
        for cut in range(1, len(outer)):
            yield outer[:cut] + inner + outer[cut:]


def check_escaping(tokenizer: PromptTokenizer, entries: Sequence[Entry], where: str) -> list[str]:
    control = {entry.content: tokenizer.control(entry.content) for entry in entries}
    found = [
        f"{where}: trusted text {content!r} no longer encodes to its control id"
        for content, token_id in control.items()
        if tokenizer.encode_trusted(content) != [token_id]
    ]
    ids = set(control.values())
    for probe in probes(list(control)):
        encoded = tokenizer.encode_text(probe)
        if ids.intersection(encoded):
            found.append(f"{where}: untrusted text {probe!r} produced a control id")
        elif tokenizer.decode(encoded) != probe:
            found.append(f"{where}: untrusted text {probe!r} does not decode back to itself")
    return found


def violations(reasons: Sequence[str], path: str) -> list[Violation]:
    return [Violation(path, 1, reason) for reason in dict.fromkeys(reasons)]


def find_violations(root: Path) -> list[Violation]:
    try:
        token_list = load_token_list(root)
    except TokenListError as error:
        return [Violation(TOKENS_FILE, 1, str(error))]
    tokenizer = PromptTokenizer(listed_tokenizer(token_list.entries))
    return violations(check_escaping(tokenizer, token_list.entries, "listed"), TOKENS_FILE)


def recorded_difference(token_list: TokenList, model_dir: Path) -> list[str]:
    raw = (model_dir / TOKENIZER_FILE).read_bytes()
    found = (
        [] if sha256(raw).hexdigest() == token_list.digest else ["tokenizer.json sha256 differs"]
    )
    real = cast(list[dict[str, Any]], json.loads(raw)["added_tokens"])
    actual = tuple(
        Entry(row["id"], row["content"], tuple((name, row[name]) for name in ATTRIBUTES))
        for row in real
    )
    if actual != token_list.entries:
        found.append("added tokens in tokenizer.json differ from the committed list")
    return found


def find_real_violations(root: Path, model_dir: Path) -> list[Violation]:
    where = str(model_dir)
    try:
        token_list = load_token_list(root)
        tokenizer = PromptTokenizer.from_dir(model_dir)
    except (TokenListError, OSError, ValueError) as error:
        return [Violation(TOKENS_FILE, 1, f"{where}: {error}")]
    reasons = [f"{where}: {text}" for text in recorded_difference(token_list, model_dir)]
    reasons.extend(check_escaping(tokenizer, token_list.entries, where))
    return violations(reasons, TOKENS_FILE)


def main(argv: Sequence[str] | None = None) -> int:
    parser = guardlib.make_parser("Check that no added or special token string can be forged.")
    parser.add_argument("--model-dir", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    root = args.root.resolve()
    found = find_violations(root)
    for model_dir in args.model_dir:
        found.extend(find_real_violations(root, model_dir.expanduser()))
    return guardlib.report(found)


if __name__ == "__main__":
    sys.exit(main())
