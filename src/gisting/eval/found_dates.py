from gisting.eval.data_model import GraderData
from gisting.eval.dates import DateRef, dated_spans, same_day, times_in
from gisting.eval.found_facts import FoundFacts


def day_label(ref: DateRef) -> str:
    return f"{ref.month:02d}-{ref.day:02d}"


def listed(ref: DateRef, days: tuple[DateRef, ...]) -> bool:
    return any(same_day(ref, day) for day in days)


def format_problems(text: str, data: GraderData) -> list[str]:
    found = [
        f"time_of_day:{ref.hour:02d}:{ref.minute:02d}" for ref in times_in(text, data.vocabulary)[0]
    ]
    for pattern in data.style.readable_date_forbidden:
        match = pattern.search(text)
        if match:
            found.append(f"date_not_readable:{match.group()}")
    return found


def role_problems(spans: list[tuple[int, DateRef]], facts: FoundFacts) -> list[str]:
    known = (*facts.estimated, *facts.delivered)
    return [
        f"date_not_a_delivery_date:{day_label(ref)}"
        for _, ref in spans
        if listed(ref, facts.others) and not listed(ref, known)
    ]


def marker_problems(
    text: str, spans: list[tuple[int, DateRef]], facts: FoundFacts, data: GraderData
) -> list[str]:
    found: list[str] = []
    for start, ref in spans:
        if not listed(ref, facts.estimated) or listed(ref, facts.delivered):
            continue
        before = data.style.sentence_break.split(text[:start])[-1].split()
        window = " ".join(before[-data.found.marker_window_words :])
        if not any(marker.search(window) for marker in data.found.estimate_markers):
            found.append(f"date_without_estimate_marker:{day_label(ref)}")
    return found


def repeat_problems(spans: list[tuple[int, DateRef]], allowed: int) -> list[str]:
    days = [day_label(ref) for _, ref in spans]
    return [f"repeated:{day}" for day in dict.fromkeys(days) if days.count(day) > allowed]


def date_problems(text: str, facts: FoundFacts, data: GraderData) -> list[str]:
    spans = dated_spans(text, data.vocabulary)
    return [
        *format_problems(text, data),
        *role_problems(spans, facts),
        *marker_problems(text, spans, facts, data),
        *repeat_problems(spans, max(1, facts.shipments)),
    ]
