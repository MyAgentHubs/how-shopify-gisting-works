import re
from dataclasses import dataclass

from gisting.eval.data_model import Vocabulary

DIGITS = re.compile(r"\d+")
TWO_DIGIT_YEAR = 100
CENTURY = 2000
HALF_DAY = 12


@dataclass(frozen=True)
class DateRef:
    year: int | None
    month: int
    day: int


@dataclass(frozen=True)
class TimeRef:
    hour: int
    minute: int
    meridiem: str | None


def number_of(token: str | None, words: dict[str, int]) -> int | None:
    if token is None:
        return None
    lowered = token.lower().rstrip(".")
    if lowered in words:
        return words[lowered]
    digits = DIGITS.match(lowered)
    return int(digits.group()) if digits else None


def date_from(match: re.Match[str], vocab: Vocabulary) -> DateRef:
    groups = match.groupdict()
    year = number_of(groups.get("year"), {})
    if year is not None and year < TWO_DIGIT_YEAR:
        year += CENTURY
    month = number_of(groups.get("month"), vocab.months) or 0
    day = number_of(groups.get("day"), vocab.day_words) or 0
    return DateRef(year, month, day)


def dates_in(text: str, vocab: Vocabulary) -> tuple[list[DateRef], str]:
    found: list[DateRef] = []
    for pattern in vocab.date_patterns:
        found.extend(date_from(match, vocab) for match in pattern.finditer(text))
        text = pattern.sub(" ", text)
    return found, text


def dated_spans(text: str, vocab: Vocabulary) -> list[tuple[int, DateRef]]:
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, DateRef]] = []
    for pattern in vocab.date_patterns:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < other_end and other_start < end for other_start, other_end in taken):
                continue
            taken.append((start, end))
            found.append((start, date_from(match, vocab)))
    return sorted(found, key=lambda item: item[0])


def months_in(text: str, vocab: Vocabulary) -> set[int]:
    return {number for number, pattern in vocab.month_only if pattern.search(text)}


def times_in(text: str, vocab: Vocabulary) -> tuple[list[TimeRef], str]:
    found: list[TimeRef] = []
    for pattern in vocab.time_patterns:
        for match in pattern.finditer(text):
            groups = match.groupdict()
            minute = int(groups.get("minute") or 0)
            found.append(TimeRef(int(groups["hour"]), minute, groups.get("meridiem")))
        text = pattern.sub(" ", text)
    return found, text


def clock_of(ref: TimeRef) -> tuple[int, int]:
    if ref.meridiem:
        afternoon = HALF_DAY if ref.meridiem.lower() == "p" else 0
        return ref.hour % HALF_DAY + afternoon, ref.minute
    return ref.hour, ref.minute


def same_day(answer: DateRef, source: DateRef) -> bool:
    if (answer.month, answer.day) != (source.month, source.day):
        return False
    return answer.year is None or source.year is None or answer.year == source.year
