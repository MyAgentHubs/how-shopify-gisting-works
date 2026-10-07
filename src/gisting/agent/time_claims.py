import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from gisting.agent.conclusions import APOSTROPHES
from gisting.prompt.files import PROMPTS_DIR
from gisting.shopify.jsonvalue import (
    Json,
    MalformedResponse,
    required_str,
    string_list,
)

TIME_WORDS_FILE = PROMPTS_DIR / "time_words.json"
UNSUPPORTED_TIME_CLAIM = "unsupported_time_claim"
MONTHS_SLOT = "<months>"
WEEKDAYS_SLOT = "<weekdays>"
AMOUNT_SLOT = "<amount>"
MONTHS_PER_YEAR = 12
DAYS_PER_WEEK = 7
DASHES = str.maketrans({"–": "-", "—": "-"})


@dataclass(frozen=True)
class Claim:
    key: str
    text: str


@dataclass(frozen=True)
class TimeRules:
    months: tuple[re.Pattern[str], ...]
    weekdays: tuple[re.Pattern[str], ...]
    month_day: tuple[re.Pattern[str], ...]
    weekday: re.Pattern[str]
    question: re.Pattern[str]
    relative: tuple[re.Pattern[str], ...]
    number: re.Pattern[str]
    amounts: tuple[re.Pattern[str], ...]
    iso_date: re.Pattern[str]


def build(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        raise MalformedResponse("time_words") from error


def parse_time_rules(text: str) -> TimeRules:
    document: Json = json.loads(text)
    if not isinstance(document, dict):
        raise MalformedResponse("time_words")
    months, weekdays = string_list(document, "months"), string_list(document, "weekdays")
    amount_value = f"(?:{required_str(document, 'amount_value')})"
    if len(months) != MONTHS_PER_YEAR or len(weekdays) != DAYS_PER_WEEK:
        raise MalformedResponse("time_words")
    return TimeRules(
        tuple(build(f"(?:{item})") for item in months),
        tuple(build(f"(?:{item})") for item in weekdays),
        tuple(
            build(entry.replace(MONTHS_SLOT, "|".join(months)))
            for entry in string_list(document, "month_day")
        ),
        build(required_str(document, "weekday").replace(WEEKDAYS_SLOT, "|".join(weekdays))),
        build(required_str(document, "question")),
        tuple(build(entry) for entry in string_list(document, "relative")),
        build(required_str(document, "number")),
        tuple(
            build(entry.replace(AMOUNT_SLOT, amount_value))
            for entry in string_list(document, "amount")
        ),
        build(required_str(document, "iso_date")),
    )


def load_time_rules(path: Path = TIME_WORDS_FILE) -> TimeRules:
    return parse_time_rules(path.read_text(encoding="utf-8"))


def index_of(patterns: Sequence[re.Pattern[str]], word: str) -> int:
    return next(i for i, pattern in enumerate(patterns) if pattern.fullmatch(word))


def squeeze(text: str) -> str:
    return " ".join(text.translate(APOSTROPHES).translate(DASHES).lower().split())


def date_claims(rules: TimeRules, text: str) -> list[Claim]:
    found: list[Claim] = []
    for pattern in rules.month_day:
        for hit in pattern.finditer(text):
            month = index_of(rules.months, hit.group("month")) + 1
            found.append(Claim(f"date:{month}:{int(hit.group('day'))}", hit.group()))
    for hit in rules.weekday.finditer(text):
        found.append(Claim(f"weekday:{index_of(rules.weekdays, hit.group())}", hit.group()))
    return found


def other_claims(rules: TimeRules, text: str) -> list[Claim]:
    squeezed = squeeze(text)
    found = [Claim(f"number:{hit.group()}", hit.group()) for hit in rules.number.finditer(text)]
    for pattern in rules.relative:
        found += [Claim(f"time:{hit.group()}", hit.group()) for hit in pattern.finditer(squeezed)]
    return found


def amount_key(value: str) -> str:
    return f"{Decimal(value.replace(',', '')).normalize():f}"


def amount_claims(rules: TimeRules, text: str) -> list[Claim]:
    return [
        Claim(f"amount:{amount_key(hit.group('value'))}", hit.group())
        for pattern in rules.amounts
        for hit in pattern.finditer(text)
    ]


def claims_in(rules: TimeRules, text: str) -> list[Claim]:
    return date_claims(rules, text) + other_claims(rules, text) + amount_claims(rules, text)


def dated_claims(rules: TimeRules, text: str) -> list[Claim]:
    found: list[Claim] = []
    for hit in rules.iso_date.finditer(text):
        try:
            day = date(int(hit.group("year")), int(hit.group("month")), int(hit.group("day")))
        except ValueError:
            continue
        found.append(Claim(f"date:{day.month}:{day.day}", hit.group()))
    return found


def unsupported_claims(rules: TimeRules, said: str, sources: Iterable[str]) -> list[str]:
    allowed = {
        claim.key
        for text in sources
        for claim in claims_in(rules, text) + dated_claims(rules, text)
    }
    asserted = rules.question.sub(" ", said)
    unsupported: dict[str, str] = {}
    for claim in claims_in(rules, asserted):
        if claim.key not in allowed:
            unsupported.setdefault(claim.key, claim.text)
    return list(unsupported.values())
