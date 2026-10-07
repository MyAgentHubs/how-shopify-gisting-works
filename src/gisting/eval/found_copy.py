from gisting.eval.data_model import GraderData, Pattern
from gisting.eval.found_facts import FoundFacts
from gisting.eval.found_parcels import all_bare, lists_parcels
from gisting.eval.style import content_sentences
from gisting.eval.text import first_match, normalize


def says(patterns: tuple[Pattern, ...], text: str) -> bool:
    return first_match(patterns, text) is not None


def line_names(facts: FoundFacts, data: GraderData) -> frozenset[str]:
    names = facts.transports or ((facts.fulfillment,) if facts.fulfillment else ())
    several = lists_parcels(facts, data)
    return frozenset(
        name for name in names if not (several and name in data.found.single_parcel_lines)
    )


def on_line(facts: FoundFacts, lines: frozenset[str], data: GraderData) -> bool:
    return bool(line_names(facts, data) & lines)


def sentence_limit(facts: FoundFacts | None, data: GraderData) -> int:
    base = data.style.max_sentences
    if facts is None:
        return base
    allowed = data.style.max_sentences_by_line
    names = {*facts.transports, facts.fulfillment or ""}
    return max([base, *(allowed.get(name, base) for name in names)])


def status_problems(text: str, words: list[str], facts: FoundFacts, data: GraderData) -> list[str]:
    parts = content_sentences(text, data)
    relaxed = on_line(facts, data.found.status_anywhere_lines, data)
    spoken = normalize(" ".join(parts) if relaxed else parts[0] if parts else "")
    if words and not any(word in spoken for word in words):
        return ["reply_lacks_status" if relaxed else "first_sentence_lacks_status"]
    return []


def handoff_required(facts: FoundFacts, data: GraderData) -> bool:
    rules = data.found
    untracked = on_line(facts, rules.handoff_untracked_lines, data) and not facts.trackings
    return on_line(facts, rules.handoff_lines, data) or untracked


def handoff_problems(text: str, facts: FoundFacts, data: GraderData) -> list[str]:
    rules = data.found
    required = handoff_required(facts, data)
    offers = says(rules.handoff, text)
    found = ["missing_handoff_offer"] if required and not offers else []
    if offers and not required:
        found.append("unneeded_handoff_offer")
    if required and says(rules.contact_carrier, text):
        found.append("contact_carrier_advice")
    return found


def reassurance_problems(text: str, facts: FoundFacts, data: GraderData) -> list[str]:
    rules = data.found
    if not on_line(facts, rules.reassurance_lines, data):
        return []
    spoken = normalize(text)
    needed = all_bare(facts, data) and rules.reassurance not in spoken
    found = ["missing_reassurance"] if needed else []
    reason = first_match(rules.invented_reason, spoken.replace(rules.reassurance, " "))
    return [*found, f"invented_reason:{reason.group().lower()}"] if reason else found


def reminder_problems(text: str, facts: FoundFacts, data: GraderData) -> list[str]:
    rules = data.found
    spoken = normalize(text)
    offered = rules.reminder_offer in spoken
    required = on_line(facts, rules.reminder_lines, data)
    found = ["missing_reminder_offer"] if required and not offered else []
    if offered and not required:
        found.append("unneeded_reminder_offer")
    if on_line(facts, rules.no_thanks_lines, data) and rules.thanks in spoken:
        found.append("unneeded_thanks")
    return found


def partial_problems(text: str, facts: FoundFacts, data: GraderData) -> list[str]:
    rules = data.found
    if facts.fulfillment != rules.partial_status:
        return []
    if not says(rules.unshipped_rest, text):
        return ["missing_unshipped_part"]
    return [] if says(rules.no_date, text) else ["missing_no_details:rest_date"]


def word_problems(text: str, data: GraderData) -> list[str]:
    hit = first_match(data.found.forbidden_words, text)
    return [f"forbidden_word:{hit.group().lower()}"] if hit else []
