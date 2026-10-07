import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from gisting.kb.aliases import Aliases
from gisting.kb.entries import Entry
from gisting.kb.params import Bm25Params

TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Hit:
    id: str
    score: float
    category: str
    version: int
    title: str
    answer: str
    matched_terms: int
    method: Literal["bm25"] = "bm25"


@dataclass(frozen=True)
class Index:
    entries: tuple[Entry, ...]
    frequencies: tuple[Mapping[str, float], ...]
    document_frequency: Mapping[str, int]
    average_length: float
    params: Bm25Params


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(TOKEN.findall(text.lower()))


def weighted_frequencies(entry: Entry, aliases: Aliases, params: Bm25Params) -> Mapping[str, float]:
    fields = (
        (entry.title, params.title_weight),
        (entry.answer, params.answer_weight),
        (" ".join(aliases.get(entry.id, ())), params.alias_weight),
    )
    totals: dict[str, float] = {}
    for text, weight in fields:
        if weight:
            for term, count in Counter(tokenize(text)).items():
                totals[term] = totals.get(term, 0.0) + count * weight
    return totals


def build_index(
    entries: tuple[Entry, ...], params: Bm25Params, aliases: Aliases | None = None
) -> Index:
    frequencies = tuple(weighted_frequencies(entry, aliases or {}, params) for entry in entries)
    document_frequency = Counter(term for counts in frequencies for term in counts)
    total = sum(sum(counts.values()) for counts in frequencies)
    return Index(
        entries=entries,
        frequencies=frequencies,
        document_frequency=document_frequency,
        average_length=total / len(entries) if entries else 0.0,
        params=params,
    )


def inverse_document_frequency(index: Index, term: str) -> float:
    containing = index.document_frequency.get(term, 0)
    return math.log(1 + (len(index.entries) - containing + 0.5) / (containing + 0.5))


def score_document(index: Index, position: int, terms: tuple[str, ...]) -> tuple[float, int]:
    counts = index.frequencies[position]
    length = sum(counts.values())
    params = index.params
    norm = 1 - params.b + params.b * length / index.average_length
    total = 0.0
    matched = 0
    for term in terms:
        frequency = counts.get(term, 0)
        if frequency:
            matched += 1
            weight = frequency * (params.k1 + 1) / (frequency + params.k1 * norm)
            total += inverse_document_frequency(index, term) * weight
    return total, matched


def search(index: Index, query: str, top_k: int) -> tuple[Hit, ...]:
    terms = tuple(sorted(set(tokenize(query)) - index.params.stopwords))
    scored = [
        (*score_document(index, position, terms), position)
        for position in range(len(index.entries))
    ]
    matched = [
        (score, count, index.entries[position]) for score, count, position in scored if score > 0
    ]
    matched.sort(key=lambda row: (-row[0], row[2].id))
    return tuple(
        Hit(entry.id, score, entry.category, entry.version, entry.title, entry.answer, count)
        for score, count, entry in matched[:top_k]
    )
