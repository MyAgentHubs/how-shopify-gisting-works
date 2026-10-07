import json

import pytest
from kb_support import real_index
from quality_support import Keep, Query, load_queries, measure

from gisting.kb.bm25 import Hit, Index
from gisting.kb.jsonvalue import KB_DIR
from gisting.kb.params import Bm25Params, load_params

FLOORS = json.loads((KB_DIR / "quality-floors-v2.json").read_text(encoding="utf-8"))["holdout"]


def thresholds(params: Bm25Params) -> Keep:
    def keep(hits: tuple[Hit, ...]) -> tuple[Hit, ...]:
        return tuple(
            hit
            for hit in hits
            if hit.score >= params.min_score and hit.matched_terms >= params.min_matched_terms
        )

    return keep


@pytest.fixture(scope="module")
def holdout() -> tuple[Query, ...]:
    return tuple(query for query in load_queries() if query.split == "holdout")


@pytest.fixture(scope="module")
def index() -> Index:
    return real_index()


def test_holdout_ranking_stays_above_the_recorded_floors(
    index: Index, holdout: tuple[Query, ...]
) -> None:
    quality = measure(index, holdout)
    assert quality.top1 >= FLOORS["min_top1"]
    assert quality.top3 >= FLOORS["min_top3"]


def test_holdout_with_thresholds_keeps_some_answers_and_rejects_negatives(
    index: Index, holdout: tuple[Query, ...]
) -> None:
    quality = measure(index, holdout, thresholds(load_params()))
    assert quality.accepted_top1 >= FLOORS["min_accepted_top1"]
    assert quality.false_hits <= FLOORS["max_false_hits"]


def test_the_thresholds_reject_more_negatives_than_ranking_alone(
    index: Index, holdout: tuple[Query, ...]
) -> None:
    assert (
        measure(index, holdout, thresholds(load_params())).false_hits
        < measure(index, holdout).false_hits
    )
