from kb_support import PARAMS, index_of

from gisting.kb.bm25 import Hit, search, tokenize
from gisting.kb.params import Bm25Params

TOP = 10


def ids(hits: tuple[Hit, ...]) -> list[str]:
    return [hit.id for hit in hits]


def test_tokenize_lowercases_and_splits_on_non_alphanumerics() -> None:
    assert tokenize("Hello, WORLD-42!") == ("hello", "world", "42")


def test_higher_term_frequency_ranks_first() -> None:
    index = index_of(("a", "apple pear plum fig"), ("b", "apple apple pear plum"))
    assert ids(search(index, "apple", TOP)) == ["b", "a"]


def test_shorter_document_wins_at_equal_term_frequency() -> None:
    index = index_of(("long", "apple pear plum fig kiwi lime"), ("short", "apple pear"))
    assert ids(search(index, "apple", TOP)) == ["short", "long"]


def test_rarer_terms_weigh_more() -> None:
    index = index_of(("a", "common rare"), ("b", "common other"), ("c", "common third"))
    assert ids(search(index, "common rare", TOP))[0] == "a"


def test_ties_break_by_id_ascending() -> None:
    index = index_of(("c", "apple pear"), ("a", "apple pear"), ("b", "apple pear"))
    assert ids(search(index, "apple", TOP)) == ["a", "b", "c"]


def test_top_k_truncates_after_ranking() -> None:
    index = index_of(("a", "apple"), ("b", "apple apple"), ("c", "apple apple apple"))
    assert len(search(index, "apple", 2)) == 2


def test_empty_and_unmatched_queries_return_no_hits() -> None:
    index = index_of(("a", "apple pear"))
    assert search(index, "", TOP) == ()
    assert search(index, "   !!! ", TOP) == ()
    assert search(index, "zebra", TOP) == ()


def test_hits_carry_method_and_entry_fields() -> None:
    hit = search(index_of(("a", "apple")), "apple", TOP)[0]
    assert (hit.method, hit.category, hit.version, hit.answer) == ("bm25", "synthetic", 1, "apple")
    assert hit.score > 0


def test_query_order_and_repeats_do_not_change_the_result() -> None:
    index = index_of(("a", "apple pear"), ("b", "pear plum"), ("c", "apple plum"))
    assert search(index, "apple pear", TOP) == search(index, "pear apple apple", TOP)


def test_stopwords_are_dropped_from_the_query_only() -> None:
    params = Bm25Params(k1=1.5, b=0.75, default_top_k=3, max_top_k=10, stopwords=frozenset({"the"}))
    index = index_of(("a", "the apple"), ("b", "the pear"), params=params)
    assert ids(search(index, "the", TOP)) == []
    assert ids(search(index, "the pear", TOP)) == ["b"]


def test_matched_terms_counts_distinct_query_terms_present_in_the_hit() -> None:
    index = index_of(("a", "apple pear plum"), ("b", "apple fig"))
    hits = search(index, "apple pear apple zebra", TOP)
    assert {hit.id: hit.matched_terms for hit in hits} == {"a": 2, "b": 1}


def test_scores_are_raw_and_not_filtered_by_the_thresholds() -> None:
    params = Bm25Params(
        k1=PARAMS.k1,
        b=PARAMS.b,
        default_top_k=3,
        max_top_k=10,
        min_score=99.0,
        min_matched_terms=5,
    )
    hits = search(index_of(("a", "apple"), params=params), "apple", TOP)
    assert [hit.id for hit in hits] == ["a"]
