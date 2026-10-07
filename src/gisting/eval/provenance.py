from gisting.eval.data_model import GraderData, Vocabulary
from gisting.eval.dates import (
    DateRef,
    TimeRef,
    clock_of,
    dates_in,
    months_in,
    same_day,
    times_in,
)
from gisting.eval.source import Source, numbers_in

STRIPPED = ".,;:!?*'"


def month_name(number: int, vocab: Vocabulary) -> str:
    return max((name for name, value in vocab.months.items() if value == number), key=len)


def date_problems(dates: list[DateRef], rest: str, source: Source, vocab: Vocabulary) -> list[str]:
    found = [
        f"date:{ref.year or '*'}-{ref.month:02d}-{ref.day:02d}"
        for ref in dates
        if not any(same_day(ref, known) for known in source.dates)
    ]
    unseen = sorted(months_in(rest, vocab) - source.months)
    return [*found, *(f"month:{month_name(number, vocab)}" for number in unseen)]


def time_problems(times: list[TimeRef], source: Source) -> list[str]:
    return [
        f"time:{ref.hour:02d}:{ref.minute:02d}"
        for ref in times
        if clock_of(ref) not in source.times
    ]


def number_problems(rest: str, source: Source, data: GraderData) -> list[str]:
    ints, literals = numbers_in(rest, data)
    found = [f"invented_number:{n}" for n in sorted(ints - source.ints)]
    return [*found, *(f"invented_number:{n}" for n in sorted(literals - source.literals))]


def number_word_problems(rest: str, source: Source, vocab: Vocabulary) -> list[str]:
    return [
        f"number_word:{word.word}"
        for word in vocab.number_words
        if word.pattern.search(rest)
        and word.value not in source.ints
        and not word.pattern.search(source.text)
    ]


def weekday_problems(answer: str, source: Source, vocab: Vocabulary) -> list[str]:
    return [
        f"weekday:{day.name}"
        for day in vocab.weekdays
        if day.pattern.search(answer) and not day.pattern.search(source.text)
    ]


def relative_problems(answer: str, source: Source, vocab: Vocabulary) -> list[str]:
    found: list[str] = []
    for pattern in vocab.relative:
        match = pattern.search(answer)
        if match and not pattern.search(source.text):
            found.append(f"relative_time:{match.group().lower()}")
    return found


def names_a_day_or_month(name: str, vocab: Vocabulary) -> bool:
    return name in vocab.months or any(day.pattern.fullmatch(name) for day in vocab.weekdays)


def carrier_problems(answer: str, source: Source, vocab: Vocabulary) -> list[str]:
    known = source.text.lower()
    found = [
        f"carrier:{match.group().lower()}"
        for pattern in vocab.carriers
        if (match := pattern.search(answer)) and not pattern.search(source.text)
    ]
    for match in vocab.carrier_prefix.finditer(answer):
        name = match.group(1).strip(STRIPPED).lower()
        unknown = name not in known and name not in vocab.neutral_entities
        if name and unknown and not names_a_day_or_month(name, vocab):
            found.append(f"carrier:{name}")
    return found


def tracking_problems(answer: str, source: Source, vocab: Vocabulary) -> list[str]:
    known = source.text.lower()
    tokens = [*vocab.tracking_token.findall(answer)]
    tokens += [match.group(1) for match in vocab.tracking_label.finditer(answer)]
    return [f"tracking:{token}" for token in tokens if token.lower() not in known]


def provenance_problems(answer: str, source: Source, data: GraderData) -> list[str]:
    vocab = data.vocabulary
    dates, rest = dates_in(answer, vocab)
    times, rest = times_in(rest, vocab)
    return [
        *date_problems(dates, rest, source, vocab),
        *time_problems(times, source),
        *number_problems(rest, source, data),
        *number_word_problems(data.parcel_labels.sub(" ", rest), source, vocab),
        *weekday_problems(answer, source, vocab),
        *relative_problems(answer, source, vocab),
        *carrier_problems(answer, source, vocab),
        *tracking_problems(answer, source, vocab),
    ]
