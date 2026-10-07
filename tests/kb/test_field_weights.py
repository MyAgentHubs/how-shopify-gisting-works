import dataclasses

import pytest
from kb_support import PARAMS, entry

from gisting.kb.bm25 import build_index, search
from gisting.kb.entries import Entry
from gisting.kb.params import in_range


def titled(entry_id: str, title: str, answer: str) -> Entry:
    return dataclasses.replace(entry(entry_id, answer), title=title)


ENTRIES = (titled("kb-a", "melon", "plain words here"), titled("kb-b", "plain", "melon words here"))
ALIASES = {"kb-a": ("kiwi",), "kb-b": ("lime",)}


def first(query: str, **weights: float) -> str:
    params = dataclasses.replace(PARAMS, **weights)
    return search(build_index(ENTRIES, params, ALIASES), query, 1)[0].id


def test_a_term_only_in_the_aliases_is_found() -> None:
    assert first("kiwi") == "kb-a"
    assert first("lime") == "kb-b"


def test_a_zero_alias_weight_ignores_the_aliases() -> None:
    index = build_index(ENTRIES, dataclasses.replace(PARAMS, alias_weight=0.0), ALIASES)
    assert search(index, "kiwi", 3) == ()


def test_title_weight_decides_between_a_title_match_and_an_answer_match() -> None:
    assert first("melon", title_weight=3.0, answer_weight=1.0) == "kb-a"
    assert first("melon", title_weight=1.0, answer_weight=3.0) == "kb-b"


def test_the_alias_weight_scales_the_score() -> None:
    def score(weight: float) -> float:
        params = dataclasses.replace(PARAMS, alias_weight=weight)
        return search(build_index(ENTRIES, params, ALIASES), "kiwi", 1)[0].score

    assert score(2.0) > score(1.0) > score(0.5)


def test_an_entry_without_aliases_is_indexed_from_title_and_answer_only() -> None:
    assert search(build_index(ENTRIES, PARAMS, {}), "kiwi", 3) == ()


def test_matched_terms_count_alias_terms() -> None:
    index = build_index(ENTRIES, PARAMS, {"kb-a": ("kiwi lime",)})
    assert search(index, "kiwi lime", 1)[0].matched_terms == 2


@pytest.mark.parametrize(
    "weights",
    [
        {"title_weight": -1.0},
        {"alias_weight": -0.1},
        {"title_weight": 0.0, "answer_weight": 0.0, "alias_weight": 0.0},
    ],
)
def test_out_of_range_weights_are_rejected(weights: dict[str, float]) -> None:
    assert not in_range(dataclasses.replace(PARAMS, **weights))
