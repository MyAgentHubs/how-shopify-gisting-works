from dataclasses import dataclass
from typing import Annotated, Literal

from gisting.kb.entries import ENTRY_ID, MAX_ID_LENGTH
from gisting.prompt.schema_marks import MaxItems, MaxLength, Pattern

PublicOutcomeName = Literal["completed", "unavailable", "locked"]
KnowledgeMethod = Literal["bm25"]
MAX_KNOWLEDGE = 3
KnowledgeId = Annotated[str, Pattern(f"^{ENTRY_ID.pattern}$"), MaxLength(MAX_ID_LENGTH)]


@dataclass(frozen=True)
class PublicToolCall:
    tool: str
    order_number: str | None
    outcome: PublicOutcomeName


@dataclass(frozen=True)
class PublicKnowledge:
    id: KnowledgeId
    method: KnowledgeMethod


@dataclass(frozen=True)
class PublicTokens:
    rules: int
    tools: int
    history: int
    tool_results: int
    total: int


@dataclass(frozen=True)
class PublicLatency:
    first_token_ms: float
    total_ms: float


@dataclass(frozen=True)
class PublicTrace:
    tools: tuple[PublicToolCall, ...]
    knowledge: Annotated[tuple[PublicKnowledge, ...], MaxItems(MAX_KNOWLEDGE)]
    tokens: PublicTokens
    latency: PublicLatency
