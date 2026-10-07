import json
from pathlib import Path

from gisting.kb.bm25 import build_index, search
from gisting.kb.entries import parse_entries
from gisting.kb.params import parse_params
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.lookup_order import ToolResponse
from gisting.tools.search_policy import SearchPolicy

PARAMS: JsonObject = {
    "k1": 1.5,
    "b": 0.75,
    "default_top_k": 3,
    "max_top_k": 10,
    "stopwords": [],
    "min_score": 0.0,
    "min_matched_terms": 0,
}


def entry_row(entry_id: str, answer: str) -> str:
    return json.dumps({
        "id": entry_id,
        "category": "synthetic",
        "version": 1,
        "valid_from": "2026-01-01",
        "source": "test",
        "title": f"title of {entry_id}",
        "answer": answer,
    })


def build(tmp_path: Path, answers: dict[str, str], **params: float) -> SearchPolicy:
    entries = tmp_path / "entries.jsonl"
    entries.write_text("\n".join(entry_row(key, text) for key, text in answers.items()) + "\n")
    parameters = tmp_path / "params.json"
    parameters.write_text(json.dumps({**PARAMS, **params}))
    return SearchPolicy(entries, parameters, None)


def raw_score(answers: dict[str, str], query: str) -> float:
    text = "\n".join(entry_row(key, value) for key, value in answers.items())
    index = build_index(parse_entries(text, "t"), parse_params(PARAMS))
    return search(index, query, 1)[0].score


def hits_of(response: ToolResponse) -> list[JsonObject]:
    hits = response.result.get("hits")
    assert isinstance(hits, list)
    return [hit for hit in hits if isinstance(hit, dict)]


def hit_ids(response: ToolResponse) -> list[str]:
    return [str(hit["id"]) for hit in hits_of(response)]
