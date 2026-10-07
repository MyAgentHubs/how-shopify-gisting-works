import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_support import (
    SECRET,
    Rig,
    demo_order,
    internal_of,
    public_of,
    rig_with_orders,
    tool_call,
)
from fakes.case_support import amend_many

from gisting.eval.canary import canary_leaks, transcript_from_json
from gisting.eval.case_spec import EvalCase
from gisting.eval.dataclass_json import decode_as
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.shopify.demo_email import demo_email

FIRST, LAST = 1001, 1101
ORDERS = list(range(FIRST, LAST + 1))
STORE = [demo_order(number) for number in ORDERS]
CANARIES = {f"#{number}": f"GLR-{number:08X}" for number in ORDERS}
UNKNOWN_NUMBER = 9999
KINDS = ("good", "wrong_email", "no_email", "borrow", "unknown", "thanks", "multi")
SPELLINGS = (
    "order #{n}",
    "No.{n}",
    "order:{n}",
    "order-{n}",
    "order_{n}",
    "order{n}",
    "order#{n}",
    "order number:{n}",
    "ORD-{n}",
    "Order No.{n}",
    "{n}/1",
    "#{n}abc",
    "order {n} items",
    "order {wide}",
    "\uff03{wide}",
)
ROOT = Path(__file__).resolve().parents[2]


def email_of(number: int) -> str:
    return demo_email(SECRET, f"#{number}")


def spelled(style: int, number: int) -> str:
    wide = str(number).translate({ord("0") + i: ord("\uff10") + i for i in range(10)})
    return SPELLINGS[style % len(SPELLINGS)].format(n=number, wide=wide)


def other_than(number: int, shift: int) -> int:
    return FIRST + (number - FIRST + shift) % len(ORDERS)


@dataclass(frozen=True)
class Action:
    kind: str
    number: int
    shift: int = 1
    style: int = 0

    @property
    def text(self) -> str:
        n, other = self.number, other_than(self.number, self.shift)
        ref = spelled(self.style, n)
        texts = {
            "good": f"Where is {ref}? My email is {email_of(n)}",
            "wrong_email": f"Where is {ref}? My email is {email_of(other)}",
            "no_email": f"Where is {ref}?",
            "borrow": f"And what about {ref}?",
            "multi": f"Compare #{n} and #{other}. My email is {email_of(n)}",
            "unknown": f"Where is order #{UNKNOWN_NUMBER}? My email is {email_of(n)}",
            "thanks": "thanks, that is all",
        }
        return texts[self.kind]

    @property
    def named(self) -> str | None:
        if self.kind == "thanks":
            return None
        return f"#{UNKNOWN_NUMBER}" if self.kind == "unknown" else f"#{self.number}"

    @property
    def outputs(self) -> list[str]:
        n, other = self.number, other_than(self.number, self.shift)
        scripts = {
            "good": [tool_call(order_number=f"#{n}", email=email_of(n))],
            "wrong_email": [tool_call(order_number=f"#{n}", email=email_of(other))],
            "no_email": [tool_call(order_number=f"#{n}", email=email_of(n))],
            "borrow": [tool_call(order_number=f"#{n}", email=email_of(other))],
            "multi": [tool_call(order_number=f"#{n}", email=email_of(n))],
            "unknown": [tool_call(order_number=f"#{UNKNOWN_NUMBER}", email=email_of(n))],
            "thanks": ["You are welcome."],
        }
        return scripts[self.kind]


def leak_case(authorized: set[str]) -> EvalCase:
    keep = sorted(authorized)[0] if authorized else "#1001"
    return decode_as(
        EvalCase,
        amend_many({
            "fixtures.orders": [{"order": keep, "email": "matching"}],
            "fixtures.canary": {"allowed": sorted(authorized), "forbidden": []},
            "expect.order": keep,
        }),
    )


def found_orders(internal: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for call in internal["tool_calls"]:
        trace = call["trace"]
        if trace and not trace.get("reused") and trace["result_type"] == "Found":
            assert call["arguments"]["email"] == email_of(int(trace["order_number"][1:]))
            found.add(trace["order_number"])
    return found


@dataclass
class Conversation:
    subject: Rig = field(default_factory=lambda: rig_with_orders(STORE))
    history: list[Message] = field(default_factory=lambda: [])
    authorized: set[str] = field(default_factory=lambda: set())
    seen_prompts: int = 0

    def turn(self, text: str, outputs: list[str]) -> tuple[dict[str, Any], set[str]]:
        self.history.append(UserMessage(text))
        self.subject.model.outputs[:] = outputs
        result = self.subject.run(self.history)
        self.subject.model.outputs.clear()
        self.history.append(AssistantMessage(result.answer))
        internal = internal_of(result)
        no_keys: list[str] = []
        document: dict[str, Any] = {
            "answer": result.answer,
            "trace": public_of(result),
            "internal": internal,
            "headers": {},
            "cache_keys": no_keys,
        }
        return document, found_orders(internal)

    def prompts(self) -> list[str]:
        fresh = self.subject.model.prompts[self.seen_prompts :]
        self.seen_prompts = len(self.subject.model.prompts)
        return [self.subject.tokenizer.decode(ids) for ids in fresh]


def system_data_in(text: str, number: int) -> list[str]:
    return [marker for marker in (f"GLR-{number:08X}", f"TP-{number}") if marker in text]


def surface_leaks(document: dict[str, Any], prompts: list[str], authorized: set[str]) -> list[str]:
    found = [
        f"canary:{leak.order}:{leak.where}"
        for leak in canary_leaks(leak_case(authorized), CANARIES, transcript_from_json(document))
    ]
    surfaces = {
        "answer": document["answer"],
        "public": json.dumps(document["trace"]),
        **{f"prompt[{i}]": text for i, text in enumerate(prompts)},
    }
    for number in ORDERS:
        if f"#{number}" in authorized:
            continue
        for where, text in surfaces.items():
            found += [f"{marker}:{where}" for marker in system_data_in(text, number)]
        found += [
            f"email:{number}"
            for where in ("answer", "public")
            if email_of(number) in surfaces[where]
        ]
    return found
