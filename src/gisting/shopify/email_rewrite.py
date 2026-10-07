import re
from dataclasses import dataclass

from gisting.shopify.apply_order import (
    ApplyContext,
    OrderOutcome,
    Status,
    describe,
    report,
)
from gisting.shopify.assess import Step, email_status
from gisting.shopify.client import Verified
from gisting.shopify.demo_email import demo_email
from gisting.shopify.jsonvalue import JsonObject
from gisting.shopify.order_state import OrderState
from gisting.shopify.plan import PlanEntry, format_time
from gisting.shopify.results import Failure, NotExecuted, Ok, Uncertain

WRITE_ATTEMPTS = 2
EMAIL_PATTERN = re.compile(r"[\w.+%-]+@[\w-]+(?:\.[\w-]+)+")
MASK = "[email]"


def email_variables(state: OrderState, expected: str) -> JsonObject:
    return {"input": {"id": state.id, "email": expected}}


@dataclass(frozen=True)
class EmailRewrite:
    ctx: ApplyContext
    entry: PlanEntry
    expected: str

    def finish(self, status: Status, detail: str = "") -> OrderOutcome:
        return report(self.ctx, self.entry, status, EMAIL_PATTERN.sub(MASK, detail))

    def run(self) -> OrderOutcome:
        for attempt in range(WRITE_ATTEMPTS):
            outcome = self.attempt(attempt)
            if outcome is not None:
                return outcome
        return self.settle_unresolved()

    def look(self, *, after_write: bool) -> OrderState | OrderOutcome:
        state = self.ctx.client.fetch_order(self.entry.order)
        if isinstance(state, OrderState):
            return state
        if after_write:
            return self.finish(Status.UNCERTAIN, f"readback failed: {describe(state)}")
        status = Status.REFUSED if isinstance(state, NotExecuted) else Status.FAILED
        return self.finish(status, describe(state))

    def matches(self, state: OrderState) -> bool:
        return email_status(state, self.expected) == "matches"

    def attempt(self, attempt: int) -> OrderOutcome | None:
        state = self.look(after_write=attempt > 0)
        if isinstance(state, OrderOutcome):
            return state
        verified = self.ctx.client.writable(state)
        if isinstance(verified, NotExecuted):
            return self.finish(Status.REFUSED, describe(verified))
        if self.matches(state):
            detail = "confirmed after an uncertain write" if attempt else ""
            return self.finish(Status.APPLIED if attempt else Status.UNCHANGED, detail)
        return self.write(state, verified, attempt)

    def write(self, state: OrderState, verified: Verified, attempt: int) -> OrderOutcome | None:
        self.record_intent(attempt)
        result = self.ctx.client.write(
            verified, Step.UPDATE_ORDER.value, email_variables(state, self.expected)
        )
        if isinstance(result, Uncertain):
            return None
        if isinstance(result, Ok):
            return self.verify(None)
        return self.refused_or_verify(result)

    def refused_or_verify(self, failure: Failure) -> OrderOutcome:
        if isinstance(failure, NotExecuted):
            return self.finish(Status.REFUSED, describe(failure))
        return self.verify(describe(failure))

    def record_intent(self, attempt: int) -> None:
        self.ctx.ledger.record({
            "kind": "intent",
            "at": format_time(self.ctx.clock()),
            "order": self.entry.order,
            "step": Step.UPDATE_ORDER.value,
            "attempt": attempt + 1,
        })

    def verify(self, problem: str | None) -> OrderOutcome:
        state = self.look(after_write=True)
        if isinstance(state, OrderOutcome):
            return state
        status = email_status(state, self.expected)
        if problem is not None:
            return self.finish(Status.FAILED, f"{problem}; effect_observed={status == 'matches'}")
        if status != "matches":
            return self.finish(Status.FAILED, f"email 回读 {status}")
        return self.finish(Status.APPLIED)

    def settle_unresolved(self) -> OrderOutcome:
        state = self.look(after_write=True)
        if isinstance(state, OrderOutcome):
            return state
        if self.matches(state):
            return self.finish(Status.APPLIED, "confirmed after an uncertain write")
        return self.finish(
            Status.UNCERTAIN, f"email not reflected after {WRITE_ATTEMPTS} uncertain writes"
        )


def rewrite_email(ctx: ApplyContext, entry: PlanEntry) -> OrderOutcome:
    return EmailRewrite(ctx, entry, demo_email(ctx.email_secret, entry.order)).run()
