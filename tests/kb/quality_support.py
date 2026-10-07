import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gisting.kb.bm25 import Hit, Index, search

QUERIES_FILE = Path(__file__).resolve().parents[2] / "kb" / "queries-v1.jsonl"
TOP = 3
Keep = Callable[[tuple[Hit, ...]], tuple[Hit, ...]]


@dataclass(frozen=True)
class Query:
    id: str
    query: str
    expect_ids: tuple[str, ...]
    split: str


@dataclass(frozen=True)
class Quality:
    positives: int
    negatives: int
    top1: int
    top3: int
    accepted_top1: int
    false_hits: int


def load_queries(path: Path = QUERIES_FILE) -> tuple[Query, ...]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return tuple(
        Query(row["id"], row["query"], tuple(row["expect_ids"]), row["split"]) for row in rows
    )


def keep_all(hits: tuple[Hit, ...]) -> tuple[Hit, ...]:
    return hits


def measure(index: Index, queries: tuple[Query, ...], keep: Keep = keep_all) -> Quality:
    positives = [query for query in queries if query.expect_ids]
    negatives = [query for query in queries if not query.expect_ids]
    top1 = top3 = accepted_top1 = 0
    for query in positives:
        hits = search(index, query.query, TOP)
        ranked = [hit.id for hit in hits]
        first = bool(ranked) and ranked[0] in query.expect_ids
        top1 += first
        top3 += any(found in query.expect_ids for found in ranked)
        kept = [hit.id for hit in keep(hits)]
        accepted_top1 += bool(kept) and kept[0] in query.expect_ids
    false_hits = sum(bool(keep(search(index, query.query, TOP))) for query in negatives)
    return Quality(len(positives), len(negatives), top1, top3, accepted_top1, false_hits)
