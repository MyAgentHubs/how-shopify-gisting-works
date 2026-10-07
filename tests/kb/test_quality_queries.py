import json
from collections import Counter

import pytest
from kb_support import real_index
from quality_support import QUERIES_FILE, Query, load_queries, measure

from gisting.kb.bm25 import Index
from gisting.kb.entries import load_entries

FIELDS = {"id", "query", "expect_ids", "split"}
CATEGORY_COUNT = 13


@pytest.fixture(scope="module")
def queries() -> tuple[Query, ...]:
    return load_queries()


@pytest.fixture(scope="module")
def index() -> Index:
    return real_index()


def test_every_row_has_exactly_the_documented_fields() -> None:
    for line in QUERIES_FILE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        assert set(row) == FIELDS
        assert isinstance(row["query"], str) and row["query"] == row["query"].strip()
        assert row["split"] in {"dev", "holdout"}


def test_ids_and_query_texts_are_unique(queries: tuple[Query, ...]) -> None:
    assert len({query.id for query in queries}) == len(queries)
    assert len({query.query.lower() for query in queries}) == len(queries)


def test_expected_ids_exist_in_the_knowledge_base(queries: tuple[Query, ...]) -> None:
    known = {entry.id for entry in load_entries()}
    for query in queries:
        assert set(query.expect_ids) <= known


def test_sizes_match_the_plan(queries: tuple[Query, ...]) -> None:
    positives = [query for query in queries if query.expect_ids]
    negatives = [query for query in queries if not query.expect_ids]
    assert 80 <= len(positives) <= 100
    assert 30 <= len(negatives) <= 40
    for split in ("dev", "holdout"):
        assert abs(sum(q.split == split for q in positives) - len(positives) / 2) <= 2
        assert abs(sum(q.split == split for q in negatives) - len(negatives) / 2) <= 2


def test_every_category_is_covered_in_both_splits(queries: tuple[Query, ...]) -> None:
    category = {entry.id: entry.category for entry in load_entries()}
    for split in ("dev", "holdout"):
        covered = {category[found] for q in queries if q.split == split for found in q.expect_ids}
        assert len(covered) == CATEGORY_COUNT


def test_no_query_is_copied_from_the_knowledge_base(queries: tuple[Query, ...]) -> None:
    texts = [f"{entry.title} {entry.answer}".lower() for entry in load_entries()]
    for query in queries:
        assert not any(query.query.lower() in text for text in texts)


def test_the_two_splits_do_not_share_a_sentence_pattern(queries: tuple[Query, ...]) -> None:
    def openings(split: str) -> Counter[str]:
        return Counter(" ".join(q.query.lower().split()[:4]) for q in queries if q.split == split)

    assert not set(openings("dev")) & set(openings("holdout"))


def test_quality_is_computable_for_each_split_under_the_default_parameters(
    queries: tuple[Query, ...], index: Index
) -> None:
    for split in ("dev", "holdout"):
        quality = measure(index, tuple(q for q in queries if q.split == split))
        assert quality.positives > 0 and quality.negatives > 0
        assert 0 <= quality.top1 <= quality.top3 <= quality.positives
        assert quality.accepted_top1 == quality.top1
        assert 0 <= quality.false_hits <= quality.negatives
