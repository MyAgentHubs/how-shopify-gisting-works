import io
import json
import sys
from pathlib import Path
from typing import cast

import pytest
from kb_support import entry
from quality_support import load_queries

from gisting.kb.aliases import ALIASES_FILE, load_aliases, parse_aliases
from gisting.kb.bm25 import tokenize
from gisting.kb.cli import main
from gisting.kb.entries import load_entries
from gisting.kb.jsonvalue import KB_DIR, KbDataError
from gisting.tools.search_policy import SearchPolicy

REPO = Path(__file__).resolve().parents[2]
ENTRIES = (entry("kb-a", "apple"), entry("kb-b", "pear"))
MIN_ALIASES = 8
MAX_ALIASES = 20


def rows() -> list[dict[str, object]]:
    lines = ALIASES_FILE.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def aliases_of(row: dict[str, object]) -> list[str]:
    value = row["aliases"]
    assert isinstance(value, list)
    phrases: list[str] = []
    for alias in cast("list[object]", value):
        phrases.append(str(alias))
    return phrases


def special_tokens() -> list[str]:
    document = json.loads((REPO / "prompts" / "qwen3_added_tokens.json").read_text("utf-8"))
    return [token["content"] for token in document["added_tokens"]]


def test_the_default_aliases_file_is_the_v1_file() -> None:
    assert ALIASES_FILE == KB_DIR / "policy-aliases-v1.jsonl"


def test_every_alias_row_names_an_existing_entry_exactly_once() -> None:
    known = {entry_row.id for entry_row in load_entries()}
    ids = [str(row["id"]) for row in rows()]
    assert set(ids) <= known
    assert len(set(ids)) == len(ids)
    assert set(ids) == known


def test_every_row_has_exactly_id_and_a_bounded_list_of_distinct_phrases() -> None:
    for row in rows():
        assert set(row) == {"id", "aliases"}
        phrases = aliases_of(row)
        assert MIN_ALIASES <= len(phrases) <= MAX_ALIASES
        assert len({phrase.lower() for phrase in phrases}) == len(phrases)
        assert all(phrase == phrase.strip() and phrase for phrase in phrases)


def test_no_alias_contains_a_special_token_string() -> None:
    tokens = special_tokens()
    assert tokens
    for row in rows():
        for phrase in aliases_of(row):
            assert not any(token in phrase for token in tokens)


def test_no_alias_is_a_labelled_query() -> None:
    queries = {" ".join(tokenize(query.query)) for query in load_queries()}
    for row in rows():
        assert not {" ".join(tokenize(phrase)) for phrase in aliases_of(row)} & queries


def test_load_aliases_maps_ids_to_phrase_tuples() -> None:
    assert set(load_aliases(load_entries())) == {entry_row.id for entry_row in load_entries()}


@pytest.mark.parametrize(
    "text",
    [
        '{"id": "kb-zzz", "aliases": ["x"]}',
        '{"id": "kb-a", "aliases": []}',
        '{"id": "kb-a", "aliases": ["  "]}',
        '{"id": "kb-a", "aliases": [1]}',
        '{"id": "kb-a"}',
        '{"id": "kb-a", "aliases": ["x"], "extra": 1}',
        '{"id": "kb-a", "aliases": ["x"]}\n{"id": "kb-a", "aliases": ["y"]}',
        "[]",
        "not json",
    ],
)
def test_a_malformed_alias_file_is_a_data_error(text: str) -> None:
    with pytest.raises(KbDataError):
        parse_aliases(text, "aliases.jsonl", ENTRIES)


def foreign(row: dict[str, object]) -> list[str]:
    texts = " ".join(f"{item.title} {item.answer}" for item in load_entries()).lower()
    return [phrase.lower() for phrase in aliases_of(row) if phrase.lower() not in texts]


def test_aliases_never_appear_in_the_search_policy_result() -> None:
    tool = SearchPolicy()
    for row in rows():
        result = json.dumps(tool.call({"query": aliases_of(row)[0]}, "s").result).lower()
        assert not any(phrase in result for phrase in foreign(row))


def test_aliases_never_appear_in_the_kb_search_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for row in rows():
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"query": aliases_of(row)[0]})))
        assert main(["search"]) == 0
        output = capsys.readouterr().out.lower()
        assert json.loads(output)["hits"]
        assert not any(phrase in output for phrase in foreign(row))
