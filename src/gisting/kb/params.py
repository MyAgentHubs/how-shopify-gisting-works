from dataclasses import dataclass
from pathlib import Path

from gisting.kb.jsonvalue import (
    KB_DIR,
    JsonObject,
    KbDataError,
    optional_strings,
    parse_json,
    read_text,
    required_int,
    required_number,
)

PARAMS_FILE = KB_DIR / "bm25-v3.json"


@dataclass(frozen=True)
class Bm25Params:
    k1: float
    b: float
    default_top_k: int
    max_top_k: int
    stopwords: frozenset[str] = frozenset()
    min_score: float = 0.0
    min_matched_terms: int = 0
    title_weight: float = 1.0
    answer_weight: float = 1.0
    alias_weight: float = 1.0


def optional_number(document: JsonObject, key: str, default: float) -> float:
    return required_number(document, key) if key in document else default


def parse_params(document: JsonObject) -> Bm25Params:
    return Bm25Params(
        k1=required_number(document, "k1"),
        b=required_number(document, "b"),
        default_top_k=required_int(document, "default_top_k"),
        max_top_k=required_int(document, "max_top_k"),
        stopwords=frozenset(optional_strings(document, "stopwords")),
        min_score=optional_number(document, "min_score", 0.0),
        min_matched_terms=(
            required_int(document, "min_matched_terms") if "min_matched_terms" in document else 0
        ),
        title_weight=optional_number(document, "title_weight", 1.0),
        answer_weight=optional_number(document, "answer_weight", 1.0),
        alias_weight=optional_number(document, "alias_weight", 1.0),
    )


def in_range(params: Bm25Params) -> bool:
    return (
        params.k1 >= 0
        and 0 <= params.b <= 1
        and 1 <= params.default_top_k <= params.max_top_k
        and params.min_score >= 0
        and params.min_matched_terms >= 0
        and min(params.title_weight, params.answer_weight, params.alias_weight) >= 0
        and max(params.title_weight, params.answer_weight, params.alias_weight) > 0
        and all(word.isascii() and word.isalnum() and word.islower() for word in params.stopwords)
    )


def load_params(path: Path = PARAMS_FILE) -> Bm25Params:
    document = parse_json(read_text(path), path.name)
    if not isinstance(document, dict):
        message = f"{path.name}: must be a JSON object"
        raise KbDataError(message)
    params = parse_params(document)
    if not in_range(params):
        message = f"{path.name}: parameter out of range"
        raise KbDataError(message)
    return params
