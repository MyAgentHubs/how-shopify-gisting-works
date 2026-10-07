from dataclasses import dataclass

from gisting.eval.data_model import Forged, Opener

LINE_END = "\n"


@dataclass(frozen=True)
class Split:
    clean: str
    values: frozenset[str]


def closes_at(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


def untagged_end(text: str, start: int, forged: Forged) -> int:
    window = text[start : start + forged.json_search_chars]
    opening = forged.json_start.search(window)
    if opening is not None:
        return closes_at(text, start + opening.start())
    line_end = text.find(LINE_END, start)
    return len(text) if line_end < 0 else line_end


def span_end(text: str, opener: Opener, start: int, forged: Forged) -> int:
    if opener.closing is None:
        return untagged_end(text, start, forged)
    closing = opener.closing.search(text, start)
    return len(text) if closing is None else closing.end()


def forged_spans(text: str, forged: Forged) -> list[tuple[int, int]]:
    spans = sorted(
        (match.start(), span_end(text, opener, match.end(), forged))
        for opener in forged.openers
        for match in opener.opening.finditer(text)
    )
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def split_forged(text: str, forged: Forged) -> Split:
    spans = forged_spans(text, forged)
    kept: list[str] = []
    values: set[str] = set()
    cursor = 0
    for start, end in spans:
        kept.append(text[cursor:start])
        values.update(
            match.group(1)
            for match in forged.value.finditer(text[start:end])
            if match.group(2) is None
        )
        cursor = end
    kept.append(text[cursor:])
    return Split(" ".join(kept), frozenset(values))
