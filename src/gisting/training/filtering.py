from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from gisting.eval.case import RAW
from gisting.eval.data_model import GraderData
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.training.teacher import parse_record


@dataclass(frozen=True)
class Rejection:
    sample_id: str
    split: str
    category: str
    problems: tuple[str, ...]


@dataclass(frozen=True)
class Group:
    split: str
    category: str
    total: int
    kept: int


@dataclass(frozen=True)
class Filtered:
    kept_rows: tuple[JsonObject, ...]
    rejected: tuple[Rejection, ...]
    groups: tuple[Group, ...]


def regraded(row: JsonObject, problems: tuple[str, ...]) -> JsonObject:
    verdict: list[Json] = list(problems)
    return {**row, "verdict": {"ok": not problems, "problems": verdict}}


def filter_rows(rows: Iterable[JsonObject], data: GraderData, layer: str = RAW) -> Filtered:
    kept: list[JsonObject] = []
    rejected: list[Rejection] = []
    totals: Counter[tuple[str, str]] = Counter()
    survivors: Counter[tuple[str, str]] = Counter()
    for row in rows:
        record = parse_record(row, data, layer)
        sample, verdict = record.sample, record.verdict
        key = (sample.split, sample.category)
        totals[key] += 1
        if verdict.ok:
            kept.append(regraded(row, verdict.problems))
            survivors[key] += 1
        else:
            rejected.append(Rejection(sample.id, sample.split, sample.category, verdict.problems))
    groups = tuple(Group(*key, total, survivors[key]) for key, total in sorted(totals.items()))
    return Filtered(tuple(kept), tuple(rejected), groups)


def summary_json(filtered: Filtered) -> JsonObject:
    groups: list[Json] = [
        {"split": g.split, "category": g.category, "total": g.total, "kept": g.kept}
        for g in filtered.groups
    ]
    empty: list[Json] = [
        {"split": g.split, "category": g.category} for g in filtered.groups if g.kept == 0
    ]
    rejected: list[Json] = [
        {"id": r.sample_id, "split": r.split, "category": r.category, "problems": list(r.problems)}
        for r in filtered.rejected
    ]
    return {
        "kept": len(filtered.kept_rows),
        "rejected": len(filtered.rejected),
        "groups": groups,
        "empty_groups": empty,
        "rejections": rejected,
    }
