from gisting.eval.data_model import GraderData, Pattern, Scenario
from gisting.eval.dates import dated_spans, same_day
from gisting.eval.found_copy import (
    handoff_problems,
    partial_problems,
    reassurance_problems,
    reminder_problems,
    says,
    status_problems,
    word_problems,
)
from gisting.eval.found_dates import date_problems
from gisting.eval.found_facts import FoundFacts
from gisting.eval.found_parcels import (
    expected_days,
    lacks_date,
    lacks_tracking,
    lists_parcels,
    needs_summary,
    shown_carriers,
)
from gisting.eval.text import canned_form


def status_words(facts: FoundFacts, data: GraderData) -> tuple[list[str], list[str]]:
    rules = data.found
    pairs = [
        (facts.fulfillment, rules.fulfillment_words),
        *((name, rules.transport_words) for name in facts.transports),
    ]
    spoken = pairs[1:] if facts.transports else pairs
    words = [table[name] for name, table in spoken if name in table]
    words += [text for name in facts.transports for text in rules.status_alternatives.get(name, ())]
    words += [rules.parcel_words[name] for name, _ in pairs[1:] if name in rules.parcel_words]
    unknown = [f"unknown_status:{name}" for name, table in pairs if name and name not in table]
    return list(dict.fromkeys(words)), unknown


def repeat_problems(text: str, words: list[str], facts: FoundFacts) -> list[str]:
    low = text.lower()
    values = [*words, *(value.lower() for value in (*facts.carriers, *facts.trackings))]
    allowed = max(1, facts.shipments)
    return [f"repeated:{value}" for value in dict.fromkeys(values) if low.count(value) > allowed]


def fact_problems(text: str, facts: FoundFacts, data: GraderData) -> list[str]:
    low = text.lower()
    found: list[str] = []
    if any(carrier.lower() not in low for carrier in shown_carriers(facts, data)):
        found.append("missing_fact:carrier")
    if any(number.lower() not in low for number in facts.trackings):
        found.append("missing_fact:tracking_number")
    refs = [ref for _, ref in dated_spans(text, data.vocabulary)]
    if any(not any(same_day(ref, day) for ref in refs) for day in expected_days(facts, data)):
        found.append("missing_fact:estimated_date")
    return found


def estimate_problems(text: str, facts: FoundFacts, data: GraderData) -> list[str]:
    if expected_days(facts, data):
        return []
    hits = (pattern.search(text) for pattern in data.found.no_estimate_words)
    return [f"unsupported_estimate:{hit.group().lower()}" for hit in hits if hit][:1]


def detail_problems(text: str, facts: FoundFacts, data: GraderData) -> list[str]:
    found: list[str] = []
    if lacks_tracking(facts, data) and not says(data.found.no_tracking, text):
        found.append("missing_no_details:tracking")
    if lacks_date(facts, data) and not says(data.found.no_date, text):
        found.append("missing_no_details:date")
    return found


def slot_problems(text: str, data: GraderData) -> list[str]:
    hit = data.found.unfilled_slot.search(text)
    return [f"unfilled_slot:{hit.group()}"] if hit else []


def parcel_status_problems(text: str, facts: FoundFacts, data: GraderData) -> list[str]:
    if not lists_parcels(facts, data):
        return []
    spoken = text.replace("_", " ")
    found: list[str] = []
    for status in dict.fromkeys(facts.transports):
        scenario = data.scenarios.get(data.found.parcel_scenarios.get(status, status))
        if scenario and not any(p.search(spoken) for p in scenario.status_words):
            found.append(f"missing_parcel_status:{status}")
    return found


def shared_forbidden(
    scenario: Scenario, facts: FoundFacts | None, data: GraderData
) -> tuple[Pattern, ...]:
    if facts is None or not lists_parcels(facts, data):
        return scenario.forbidden
    names = (data.found.parcel_scenarios.get(status, status) for status in facts.transports)
    banned = [
        {p.pattern for p in data.scenarios[name].forbidden}
        for name in names
        if name in data.scenarios
    ]
    return tuple(p for p in scenario.forbidden if all(p.pattern in each for each in banned))


def is_many_parcels_reply(text: str, facts: FoundFacts | None, data: GraderData) -> bool:
    several = facts is not None and lists_parcels(facts, data)
    return several and canned_form(text) == data.found.many_parcels_reply


def found_problems(text: str, facts: FoundFacts | None, data: GraderData) -> list[str]:
    if facts is None:
        return []
    if is_many_parcels_reply(text, facts, data):
        unexpected = [] if needs_summary(facts, data) else ["unexpected_summary"]
        return [*unexpected, *word_problems(text, data)]
    words, unknown = status_words(facts, data)
    several = lists_parcels(facts, data)
    return [
        *unknown,
        *slot_problems(text, data),
        *(parcel_status_problems(text, facts, data) if several else []),
        *([] if several else status_problems(text, words, facts, data)),
        *repeat_problems(text, words, facts),
        *fact_problems(text, facts, data),
        *estimate_problems(text, facts, data),
        *detail_problems(text, facts, data),
        *handoff_problems(text, facts, data),
        *reassurance_problems(text, facts, data),
        *reminder_problems(text, facts, data),
        *partial_problems(text, facts, data),
        *word_problems(text, data),
        *date_problems(text, facts, data),
    ]
