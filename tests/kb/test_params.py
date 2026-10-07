import json
from pathlib import Path

import pytest

from gisting.kb.jsonvalue import KB_DIR, KbDataError
from gisting.kb.params import PARAMS_FILE, load_params

BASE = {"k1": 1.5, "b": 0.75, "default_top_k": 3, "max_top_k": 10}


def write(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "params.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_default_parameters_are_the_v3_file() -> None:
    assert PARAMS_FILE == KB_DIR / "bm25-v3.json"
    params = load_params()
    assert params.stopwords and params.min_score > 0 and params.min_matched_terms >= 1
    assert params.alias_weight > 0


def test_the_v2_file_still_loads_with_neutral_weights() -> None:
    params = load_params(KB_DIR / "bm25-v2.json")
    assert (params.title_weight, params.answer_weight, params.alias_weight) == (1.0, 1.0, 1.0)


def test_the_v1_file_still_loads_with_neutral_thresholds() -> None:
    params = load_params(KB_DIR / "bm25-v1.json")
    assert (params.stopwords, params.min_score, params.min_matched_terms) == (frozenset(), 0.0, 0)


def test_v3_keeps_the_v1_ranking_parameters() -> None:
    v1, v2 = load_params(KB_DIR / "bm25-v1.json"), load_params()
    assert (v1.k1, v1.b, v1.default_top_k, v1.max_top_k) == (
        v2.k1,
        v2.b,
        v2.default_top_k,
        v2.max_top_k,
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"stopwords": "the"},
        {"stopwords": [1]},
        {"stopwords": ["The"]},
        {"stopwords": ["do not"]},
        {"min_score": -1},
        {"min_score": "high"},
        {"min_matched_terms": -1},
        {"min_matched_terms": 1.5},
        {"title_weight": -1},
        {"alias_weight": "heavy"},
    ],
)
def test_a_bad_threshold_or_stopword_is_a_data_error(
    tmp_path: Path, extra: dict[str, object]
) -> None:
    with pytest.raises(KbDataError):
        load_params(write(tmp_path, {**BASE, **extra}))


def test_a_non_object_document_is_a_data_error(tmp_path: Path) -> None:
    with pytest.raises(KbDataError):
        load_params(write(tmp_path, []))
