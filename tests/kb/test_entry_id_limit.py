import json

import pytest

from gisting.kb.entries import MAX_ID_LENGTH, parse_entries
from gisting.kb.jsonvalue import KbDataError


def row(identifier: str) -> str:
    return json.dumps({
        "id": identifier,
        "category": "synthetic",
        "version": 1,
        "valid_from": "2026-01-01",
        "source": "test",
        "title": "title",
        "answer": "answer",
    })


def test_an_id_of_the_longest_allowed_length_is_accepted() -> None:
    identifier = "kb-" + "a" * (MAX_ID_LENGTH - 3)
    assert parse_entries(row(identifier), "t")[0].id == identifier


def test_an_id_one_character_too_long_is_refused() -> None:
    with pytest.raises(KbDataError, match="not a slug"):
        parse_entries(row("kb-" + "a" * (MAX_ID_LENGTH - 2)), "t")
