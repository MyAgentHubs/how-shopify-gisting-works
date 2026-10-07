from gisting.eval.data_model import GraderData
from gisting.eval.dates import DateRef
from gisting.eval.found_facts import FoundFacts, ParcelFacts


def lists_parcels(facts: FoundFacts, data: GraderData) -> bool:
    style = data.style
    from_count = style.several_parcels_from_by_line.get(
        facts.fulfillment or "", style.several_parcels_from
    )
    return facts.shipments >= from_count


def is_delivered(parcel: ParcelFacts, data: GraderData) -> bool:
    return parcel.status == data.found.delivered_status


def day_of(parcel: ParcelFacts, data: GraderData) -> tuple[DateRef, ...]:
    return parcel.delivered if is_delivered(parcel, data) else parcel.estimated


def is_bare(parcel: ParcelFacts, data: GraderData) -> bool:
    return parcel.tracking is None and not day_of(parcel, data)


def has_no_details_line(parcel: ParcelFacts, facts: FoundFacts, data: GraderData) -> bool:
    single_line = parcel.status in data.found.single_parcel_lines
    return single_line and is_bare(parcel, data) and not lists_parcels(facts, data)


def shown_carriers(facts: FoundFacts, data: GraderData) -> tuple[str, ...]:
    return tuple(
        parcel.carrier
        for parcel in facts.parcels
        if parcel.carrier and not has_no_details_line(parcel, facts, data)
    )


def expected_days(facts: FoundFacts, data: GraderData) -> tuple[DateRef, ...]:
    return tuple(
        day
        for parcel in facts.parcels
        if not is_delivered(parcel, data)
        for day in parcel.estimated
    )


def lacks_tracking(facts: FoundFacts, data: GraderData) -> bool:
    return any(p.tracking is None and not is_delivered(p, data) for p in facts.parcels)


def lacks_date(facts: FoundFacts, data: GraderData) -> bool:
    return any(not day_of(p, data) and not is_delivered(p, data) for p in facts.parcels)


def all_bare(facts: FoundFacts, data: GraderData) -> bool:
    return bool(facts.parcels) and all(is_bare(parcel, data) for parcel in facts.parcels)


def needs_summary(facts: FoundFacts, data: GraderData) -> bool:
    rules, style = data.found, data.style
    statuses = {*facts.transports, facts.fulfillment or ""}
    closing = {name for status in statuses for name in rules.closing_when.get(status, ())}
    allowed = max([style.max_sentences, *(style.max_sentences_by_line.get(s, 0) for s in statuses)])
    lead = int(facts.shipments < style.several_parcels_from)
    return facts.shipments > style.max_parcels or lead + facts.shipments + len(closing) > allowed
