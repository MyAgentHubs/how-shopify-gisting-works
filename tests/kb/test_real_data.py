import pytest
from kb_support import real_index

from gisting.kb.bm25 import Index, build_index, search
from gisting.kb.entries import load_entries
from gisting.kb.params import load_params

TOP = 3
FIRST_CATEGORY = [
    ("return window", "returns"),
    ("payment methods", "payment"),
    ("tracking number", "tracking"),
    ("shipping cost canada", "shipping-cost"),
    ("exchange", "exchanges"),
    ("holiday", "holidays"),
    ("why email", "privacy"),
    ("change address", "changes"),
    ("lost parcel", "damage"),
]


@pytest.fixture(scope="module")
def index() -> Index:
    return real_index()


@pytest.mark.parametrize(("query", "category"), FIRST_CATEGORY)
def test_a_category_keyword_query_ranks_that_category_first(
    index: Index, query: str, category: str
) -> None:
    assert search(index, query, TOP)[0].category == category


def test_a_specific_query_finds_the_expected_entry(index: Index) -> None:
    assert search(index, "free shipping", TOP)[0].id == "kb-cost-free"
    assert search(index, "damaged", TOP)[0].id == "kb-damaged"


def test_a_nonsense_query_has_no_hits(index: Index) -> None:
    assert search(index, "xyzzy", TOP) == ()


def test_every_entry_is_indexed() -> None:
    entries = load_entries()
    assert len(build_index(entries, load_params()).entries) == len(entries)
