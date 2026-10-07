import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from gisting.eval.case_files import PlanOrder, plan_orders
from gisting.eval.case_spec import (
    CanaryExpect,
    EmailKind,
    EvalCase,
    Expect,
    Fixtures,
    MessageSpec,
    OrderUse,
    PlanFile,
    RedLine,
    Role,
    Slug,
    Split,
)
from gisting.eval.dataclass_json import DecodeError, Pattern, decode_as

TEMPLATE_FILE = "data/eval/redline{line}-templates.json"
SHARED_LINES = {1: "12"}
Letter = Annotated[str, Pattern(r"^[a-d]$")]
PlanScenario = Annotated[str, Pattern(r"^[A-Z][A-Z_]*$")]
FULL_WIDTH = {ord("0") + digit: ord("０") + digit for digit in range(10)}
SLOT = re.compile(r"\{(order|num|wide|email|carrier|track)_([a-z])\}")
LEFTOVER = re.compile(r"\{(?!email_)[a-z]+_[a-z]\}")
ABSENT: EmailKind = "absent"
SEALED_SPLIT: Split = "sealed"
FIRST_TURN = "first"


class TemplateError(ValueError):
    pass


@dataclass(frozen=True)
class TemplateMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class LetterUse:
    letter: Letter
    email: EmailKind
    scenarios: tuple[PlanScenario, ...] = ()


@dataclass(frozen=True)
class FamilySpec:
    split: Split
    category: Slug
    orders: tuple[LetterUse, ...]
    allowed: tuple[Letter, ...]
    forbidden: tuple[Letter, ...]
    expect_order: Letter | None
    templates: tuple[tuple[TemplateMessage, ...], ...]
    red_line: RedLine | None = None
    scenario: Slug | None = None


@dataclass(frozen=True)
class TemplateDocument:
    version: int
    seed: int
    red_line: RedLine
    plan: PlanFile
    families: dict[str, FamilySpec]


def template_paths(root: Path, red_line: int) -> list[Path]:
    base = root / TEMPLATE_FILE.format(line=SHARED_LINES.get(red_line, red_line))
    return [base, *sorted(base.parent.glob(f"{base.stem}-*{base.suffix}"))]


def load_templates(path: Path) -> TemplateDocument:
    try:
        return decode_as(TemplateDocument, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, DecodeError) as error:
        message = f"{path.name}: {type(error).__name__}: {error}"
        raise TemplateError(message) from error


def letters_of(spec: FamilySpec) -> list[str]:
    named = {use.letter for use in spec.orders} | set(spec.allowed) | set(spec.forbidden)
    return sorted(named | ({spec.expect_order} if spec.expect_order else set()))


def slots_of(spec: FamilySpec) -> list[tuple[str, str]]:
    return [
        slot
        for template in spec.templates
        for message in template
        for slot in SLOT.findall(message.content)
    ]


def check_slots(name: str, spec: FamilySpec) -> None:
    emailed = {use.letter for use in spec.orders if use.email != ABSENT}
    declared = set(letters_of(spec))
    for kind, letter in slots_of(spec):
        if letter not in declared or (kind == "email" and letter not in emailed):
            problem = f"family {name}: slot {kind}_{letter} has no matching order"
            raise TemplateError(problem)


def check_document(document: TemplateDocument) -> None:
    for name, spec in document.families.items():
        if spec.split == SEALED_SPLIT:
            problem = f"family {name}: sealed cases are never written in plaintext (E6 flow)"
            raise TemplateError(problem)
        check_slots(name, spec)


def slot_values(letter: str, picked: PlanOrder) -> dict[str, str]:
    digits = picked.order.removeprefix("#")
    values = {
        f"{{order_{letter}}}": picked.order,
        f"{{num_{letter}}}": digits,
        f"{{wide_{letter}}}": digits.translate(FULL_WIDTH),
    }
    if picked.carrier and picked.tracking:
        values[f"{{carrier_{letter}}}"] = picked.carrier
        values[f"{{track_{letter}}}"] = picked.tracking
    return values


def fill(content: str, values: dict[str, str]) -> str:
    for slot, value in values.items():
        content = content.replace(slot, value)
    if LEFTOVER.search(content):
        message = f"unfilled slot in {content!r}"
        raise TemplateError(message)
    return content


def build_case(
    name: str,
    spec: FamilySpec,
    index: int,
    picked: dict[str, PlanOrder],
    document: TemplateDocument,
) -> EvalCase:
    values = {
        slot: value
        for letter, order in picked.items()
        for slot, value in slot_values(letter, order).items()
    }
    messages = tuple(
        MessageSpec(m.role, fill(m.content, values), ()) for m in spec.templates[index]
    )
    expect_order = picked[spec.expect_order].order if spec.expect_order else None
    return EvalCase(
        id=f"{name}_{index + 1:03d}",
        red_line=document.red_line if spec.red_line is None else spec.red_line,
        category=spec.category,
        split=spec.split,
        family=name,
        messages=messages,
        fixtures=Fixtures(
            plan=document.plan,
            orders=tuple(OrderUse(picked[use.letter].order, use.email) for use in spec.orders),
            canary=CanaryExpect(
                allowed=tuple(picked[letter].order for letter in spec.allowed),
                forbidden=tuple(picked[letter].order for letter in spec.forbidden),
            ),
        ),
        expect=Expect(FIRST_TURN, spec.scenario, expect_order),
    )


def pick_orders(
    spec: FamilySpec, letters: list[str], plan: list[PlanOrder], rng: random.Random
) -> dict[str, PlanOrder]:
    pools = {use.letter: use.scenarios for use in spec.orders if use.scenarios}
    if not pools:
        return dict(zip(letters, rng.sample(plan, len(letters)), strict=True))
    picked: dict[str, PlanOrder] = {}
    for letter in letters:
        taken = {chosen.order for chosen in picked.values()}
        scenarios = pools.get(letter)
        pool = [
            entry
            for entry in plan
            if entry.order not in taken and (not scenarios or entry.scenario in scenarios)
        ]
        if not pool:
            message = f"no plan order left for letter {letter} in scenarios {scenarios}"
            raise TemplateError(message)
        picked[letter] = rng.choice(pool)
    return picked


def family_cases(document: TemplateDocument, name: str, plan: list[PlanOrder]) -> list[EvalCase]:
    spec = document.families[name]
    letters = letters_of(spec)
    cases: list[EvalCase] = []
    for index in range(len(spec.templates)):
        rng = random.Random(f"{document.seed}/{name}/{index}")
        picked = pick_orders(spec, letters, plan, rng)
        cases.append(build_case(name, spec, index, picked, document))
    return cases


def sorted_plan(root: Path, plan: str) -> list[PlanOrder]:
    entries = plan_orders(root, plan)
    if entries is None:
        message = f"plan {plan} is missing or unreadable"
        raise TemplateError(message)
    return sorted(entries, key=lambda entry: int(entry.order.removeprefix("#")))


def check_red_line(path: Path, document: TemplateDocument, red_line: int) -> None:
    if document.red_line != red_line:
        message = f"{path.name}: red_line {document.red_line} is not the {red_line} of its name"
        raise TemplateError(message)


def build_cases(root: Path, red_line: int) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for path in template_paths(root, red_line):
        document = load_templates(path)
        check_red_line(path, document, red_line)
        check_document(document)
        repeated = sorted(seen & set(document.families))
        if repeated:
            message = f"{path.name}: family {repeated[0]} is already defined in another file"
            raise TemplateError(message)
        seen |= set(document.families)
        plan = sorted_plan(root, document.plan)
        cases += [case for name in document.families for case in family_cases(document, name, plan)]
    return cases
