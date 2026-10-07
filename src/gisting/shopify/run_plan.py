import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import TypeVar

from gisting.shopify.apply_order import ApplyContext, OrderOutcome, Status, apply_order
from gisting.shopify.plan import PlanEntry

T = TypeVar("T")
FAILURE_STATUSES = frozenset({Status.FAILED, Status.UNCERTAIN_RESOLVED, Status.REFUSED})
DEFAULT_BATCH_SIZE = 5
DEFAULT_BATCH_WAIT_SECONDS = 75.0
HTTP_BATCH_WAIT_SECONDS = 10.0
DEFAULT_MAX_FAILURES = 3
ApplyOne = Callable[[ApplyContext, PlanEntry], OrderOutcome]


@dataclass(frozen=True)
class Pacing:
    size: int = DEFAULT_BATCH_SIZE
    wait: float = DEFAULT_BATCH_WAIT_SECONDS
    sleep: Callable[[float], None] = time.sleep


class RunStopped(RuntimeError):
    def __init__(self, reason: str, outcomes: list[OrderOutcome]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.outcomes = outcomes


def paced(items: Sequence[T], pacing: Pacing) -> Iterator[T]:
    for index, item in enumerate(items):
        if index and index % pacing.size == 0:
            pacing.sleep(pacing.wait)
        yield item


def run_plan(
    ctx: ApplyContext,
    entries: Sequence[PlanEntry],
    pacing: Pacing,
    max_failures: int,
    apply: ApplyOne = apply_order,
) -> list[OrderOutcome]:
    outcomes: list[OrderOutcome] = []
    streak = 0
    for entry in paced(entries, pacing):
        outcome = apply(ctx, entry)
        outcomes.append(outcome)
        if outcome.status is Status.UNCERTAIN:
            reason = f"{entry.order} outcome unresolved: {outcome.detail}"
            raise RunStopped(reason, outcomes)
        streak = streak + 1 if outcome.status in FAILURE_STATUSES else 0
        if streak >= max_failures:
            reason = f"{streak} consecutive failures, last {entry.order}: {outcome.detail}"
            raise RunStopped(reason, outcomes)
    return outcomes
