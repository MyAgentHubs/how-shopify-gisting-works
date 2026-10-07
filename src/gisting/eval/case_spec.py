from dataclasses import dataclass
from typing import Annotated, Literal

from gisting.eval.dataclass_json import Pattern

Slug = Annotated[str, Pattern(r"^[a-z0-9][a-z0-9_]*$")]
OrderNumber = Annotated[str, Pattern(r"^#[0-9]+$")]
PlanFile = Annotated[str, Pattern(r"^[a-z0-9][a-z0-9_.-]*\.json$")]
RedLine = Literal[1, 2, 3, 4, "none"]
Split = Literal["train", "dev", "sealed"]
Role = Literal["user", "assistant", "tool"]
EmailKind = Literal["matching", "wrong", "absent"]
Turn = Literal["first", "second"]


@dataclass(frozen=True)
class ToolCallSpec:
    name: Slug
    arguments: dict[str, str]


@dataclass(frozen=True)
class MessageSpec:
    role: Role
    content: str
    tool_calls: tuple[ToolCallSpec, ...]


@dataclass(frozen=True)
class OrderUse:
    order: OrderNumber
    email: EmailKind


@dataclass(frozen=True)
class CanaryExpect:
    allowed: tuple[OrderNumber, ...]
    forbidden: tuple[OrderNumber, ...]


@dataclass(frozen=True)
class Fixtures:
    plan: PlanFile | None
    orders: tuple[OrderUse, ...]
    canary: CanaryExpect


@dataclass(frozen=True)
class Expect:
    turn: Turn
    scenario: Slug | None
    order: OrderNumber | None


@dataclass(frozen=True)
class EvalCase:
    id: Slug
    red_line: RedLine
    category: Slug
    split: Split
    family: Slug
    messages: tuple[MessageSpec, ...]
    fixtures: Fixtures
    expect: Expect
