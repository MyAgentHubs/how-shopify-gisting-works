import json
from collections.abc import Iterator
from dataclasses import dataclass

from gisting.eval.case import FIRST
from gisting.prompt.messages import AssistantMessage, Message, ToolCall, ToolMessage, UserMessage
from gisting.prompt.phrases import ReplyPhrases, load_phrases
from gisting.prompt.replies import fixed_reply
from gisting.shopify.jsonvalue import JsonObject, required_object, string_list
from gisting.tools.render import render_result
from gisting.training.draw import Draw, fill, outcome_for, rotation
from gisting.training.samples import TOOL_NAME, Sample
from gisting.training.templates import Family, families_of, quota_of, section

FAILURES = ("unavailable", "locked")
Spoken = Iterator[tuple[Family, str]]


@dataclass(frozen=True)
class Context:
    messages: tuple[Message, ...]
    order_text: str
    email: str
    number: str


@dataclass
class Setup:
    draw: Draw
    phrases: ReplyPhrases
    asks: Spoken

    def node(self, group: str) -> JsonObject:
        return section(self.draw.document, "multi_turn", group)

    def spoken(self, group: str, key: str) -> Spoken:
        families = families_of(required_object(self.node(group), key), self.draw.split)
        return rotation(families, self.draw.rng)

    def scenarios(self, group: str) -> list[str]:
        return list(string_list(self.node(group), "scenarios"))

    def count(self, group: str) -> int:
        return quota_of(self.node(group)).of(self.draw.split)


def lookup_context(setup: Setup, scenario: str) -> Context:
    draw, kind = setup.draw, scenario if scenario in FAILURES else "found"
    entry = next(draw.entries(scenario if kind == "found" else None))
    order, email = draw.order_text(entry), draw.email()
    result = render_result(outcome_for(draw, entry, kind, draw.anchor()))
    call = AssistantMessage("", (ToolCall(TOOL_NAME, {"order_number": order, "email": email}),))
    messages: tuple[Message, ...] = (
        UserMessage(fill(next(setup.asks)[1], order, email)),
        call,
        ToolMessage(json.dumps(result, ensure_ascii=False)),
        AssistantMessage(fixed_reply(setup.phrases, result)),
    )
    return Context(messages, order, email, entry.number)


@dataclass(frozen=True)
class Slot:
    category: str
    kind: str
    index: int
    family: Family


def make(
    setup: Setup,
    slot: Slot,
    messages: tuple[Message, ...],
    context: Context | None,
    scenario: str | None,
) -> Sample:
    draw = setup.draw
    number, email = (context.number, context.email) if context else (None, None)
    name = f"{draw.split}-{slot.kind}-{slot.category}-{slot.index:03d}"
    family = slot.family.name
    return Sample(
        name, draw.split, slot.category, family, slot.kind, scenario, number, email, messages
    )


def answered_turn(setup: Setup, category: str, group: str) -> list[Sample]:
    replies, scenarios = setup.spoken(group, "replies"), setup.scenarios(group)
    samples: list[Sample] = []
    for index in range(setup.count(group)):
        scenario = scenarios[index % len(scenarios)]
        context = lookup_context(setup, scenario)
        family, text = next(replies)
        messages = (*context.messages, UserMessage(text))
        samples.append(
            make(setup, Slot(category, FIRST, index, family), messages, context, scenario)
        )
    return samples


def request_turn(setup: Setup) -> list[Sample]:
    texts, scenarios = setup.spoken("handoff_request", "texts"), setup.scenarios("handoff_request")
    samples: list[Sample] = []
    for index in range(setup.count("handoff_request")):
        family, text = next(texts)
        scenario = scenarios[index // 2 % len(scenarios)]
        context = lookup_context(setup, scenario) if index % 2 else None
        prior = context.messages if context else ()
        messages = (*prior, UserMessage(text))
        slot = Slot("handoff_request", FIRST, index, family)
        samples.append(make(setup, slot, messages, context, scenario if context else None))
    return samples


def multi_turn_samples(draw: Draw) -> list[Sample]:
    rows = required_object(section(draw.document, "second_call"), "questions")
    asks = rotation(families_of(rows, draw.split), draw.rng)
    setup = Setup(draw, load_phrases(), asks)
    return [
        *request_turn(setup),
        *answered_turn(setup, "handoff_decline", "handoff_decline"),
        *answered_turn(setup, "reminder_decline", "reminder_decline"),
    ]
