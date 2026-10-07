from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    RULES = "rules"
    TOOLS = "tools"
    HISTORY = "history"
    TOOL_RESULTS = "tool_results"


@dataclass(frozen=True)
class Segment:
    kind: Kind
    ids: tuple[int, ...]


@dataclass(frozen=True)
class PromptStats:
    rules: int
    tools: int
    history: int
    tool_results: int
    total: int

    def plus(self, other: "PromptStats") -> "PromptStats":
        return PromptStats(
            self.rules + other.rules,
            self.tools + other.tools,
            self.history + other.history,
            self.tool_results + other.tool_results,
            self.total + other.total,
        )

    def as_json(self) -> dict[str, int]:
        return {
            "rules": self.rules,
            "tools": self.tools,
            "history": self.history,
            "tool_results": self.tool_results,
            "total": self.total,
        }


@dataclass(frozen=True)
class Prompt:
    segments: tuple[Segment, ...]

    @property
    def ids(self) -> list[int]:
        return [token_id for segment in self.segments for token_id in segment.ids]

    @property
    def stats(self) -> PromptStats:
        def size(kind: Kind) -> int:
            return sum(len(segment.ids) for segment in self.segments if segment.kind is kind)

        return PromptStats(
            size(Kind.RULES),
            size(Kind.TOOLS),
            size(Kind.HISTORY),
            size(Kind.TOOL_RESULTS),
            len(self.ids),
        )


def empty_stats() -> PromptStats:
    return PromptStats(0, 0, 0, 0, 0)


def total_stats(items: Sequence[PromptStats]) -> PromptStats:
    total = empty_stats()
    for item in items:
        total = total.plus(item)
    return total
