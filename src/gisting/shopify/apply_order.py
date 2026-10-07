from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from gisting.shopify.apply_steps import Job, Times, advance_state, resolve_times, step_variables
from gisting.shopify.assess import Step, assess, check_outcome, email_status
from gisting.shopify.client import AdminClient
from gisting.shopify.jsonvalue import JsonObject, MalformedResponse
from gisting.shopify.ledger import Ledger
from gisting.shopify.order_state import OrderState
from gisting.shopify.plan import PlanEntry, ShipmentPlan, format_time
from gisting.shopify.results import Failure, NotExecuted, Ok, Uncertain

MESSAGE_LIMIT = 120


class Status(StrEnum):
    APPLIED = "applied"
    SKIPPED_TAGGED = "skipped_tagged"
    SKIPPED_SAME_STATE = "skipped_same_state"
    UNCHANGED = "unchanged"
    DIVERGED = "diverged"
    REFUSED = "refused"
    FAILED = "failed"
    UNCERTAIN_RESOLVED = "uncertain_resolved"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class OrderOutcome:
    order: str
    scenario: str
    status: Status
    detail: str = ""
    steps: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApplyContext:
    client: AdminClient
    ledger: Ledger
    plan: ShipmentPlan
    email_secret: str
    clock: Callable[[], datetime]


def describe(failure: Failure) -> str:
    if isinstance(failure, Uncertain):
        return f"uncertain: {failure.reason}"
    if isinstance(failure, NotExecuted):
        return f"not executed: {failure.cause.value} {failure.detail}".strip()
    messages = [str(error.get("message", "")) for error in failure.errors]
    return "graphql errors: " + "; ".join(message[:MESSAGE_LIMIT] for message in messages)


def report(
    ctx: ApplyContext, entry: PlanEntry, status: Status, detail: str, run: "OrderRun | None" = None
) -> OrderOutcome:
    times = run.job.times if run else Times(None, None)
    steps = tuple(run.done) if run else ()
    record: JsonObject = {
        "kind": "result",
        "at": format_time(ctx.clock()),
        "order": entry.order,
        "scenario": entry.scenario,
        "status": status.value,
        "detail": detail,
        "steps": list(steps),
        "canary": entry.canary,
        "happened_at": times.happened_at,
        "estimated_delivery_at": times.estimated_delivery_at,
    }
    ctx.ledger.record(record)
    return OrderOutcome(entry.order, entry.scenario, status, detail, steps)


@dataclass
class OrderRun:
    ctx: ApplyContext
    job: Job
    state: OrderState
    tagging: bool = True
    dirty: bool = False
    done: list[str] = field(default_factory=lambda: [])

    def finish(self, status: Status, detail: str = "") -> OrderOutcome:
        return report(self.ctx, self.job.entry, status, detail, self)

    def run(self) -> OrderOutcome:
        while True:
            assessment = assess(
                self.state, self.job.entry, self.job.plan, self.job.email, tagging=self.tagging
            )
            if assessment.skip:
                return self.finish(Status.SKIPPED_TAGGED)
            if assessment.diverged is not None:
                return self.finish(Status.DIVERGED, assessment.diverged)
            step = assessment.steps[0] if assessment.steps else None
            if self.dirty and step in (None, Step.ADD_TAG):
                blocked = self.confirm()
            elif step is None:
                if not self.done:
                    return self.finish(
                        Status.SKIPPED_SAME_STATE,
                        "Nothing was written because the order already has the target state.",
                    )
                return self.finish(Status.APPLIED)
            else:
                blocked = self.perform(step)
            if blocked is not None:
                return blocked

    def confirm(self) -> OrderOutcome | None:
        refreshed = self.ctx.client.fetch_order(self.job.entry.order)
        if not isinstance(refreshed, OrderState):
            return self.finish(
                Status.FAILED, f"final verification read failed: {describe(refreshed)}"
            )
        self.state, self.dirty = refreshed, False
        problem = check_outcome(refreshed, self.job.entry, self.job.plan, self.job.email)
        return self.finish(Status.FAILED, problem) if problem else None

    def verify_email(self) -> OrderOutcome | None:
        refreshed = self.ctx.client.fetch_order(self.job.entry.order)
        if not isinstance(refreshed, OrderState):
            return self.finish(Status.FAILED, f"email readback failed: {describe(refreshed)}")
        self.state = refreshed
        status = email_status(refreshed, self.job.email)
        return None if status == "matches" else self.finish(Status.FAILED, f"email 回读 {status}")

    def perform(self, step: Step) -> OrderOutcome | None:
        if step.value in self.done:
            return self.finish(Status.FAILED, f"{step.value} was written but is not reflected")
        verified = self.ctx.client.writable(self.state)
        if isinstance(verified, NotExecuted):
            return self.finish(Status.REFUSED, describe(verified))
        variables = step_variables(step, self.state, self.job)
        self.ctx.ledger.record({
            "kind": "intent",
            "at": format_time(self.ctx.clock()),
            "order": self.job.entry.order,
            "step": step.value,
        })
        self.done.append(step.value)
        result = self.ctx.client.write(verified, step.value, variables)
        if not isinstance(result, Ok):
            return self.settle(step, result)
        return self.advance(step, result.data)

    def advance(self, step: Step, data: JsonObject) -> OrderOutcome | None:
        try:
            self.state = advance_state(step, self.state, self.job, data)
        except MalformedResponse:
            return self.settle(step, Uncertain("malformed write response"))
        if step is Step.ADD_TAG:
            return self.finish(Status.APPLIED)
        if step is Step.UPDATE_ORDER:
            return self.verify_email()
        self.dirty = True
        return None

    def settle(self, step: Step, failure: Failure) -> OrderOutcome:
        if isinstance(failure, NotExecuted):
            return self.finish(Status.FAILED, f"{step.value}: {describe(failure)}")
        refreshed = self.ctx.client.fetch_order(self.job.entry.order)
        if not isinstance(refreshed, OrderState):
            unread = describe(refreshed)
            detail = f"{step.value}: {describe(failure)}; verification read failed: {unread}"
            return self.finish(Status.UNCERTAIN, detail)
        visible = self.effect_visible(step, refreshed)
        detail = f"{step.value}: {describe(failure)}; effect_observed={visible}"
        resolved = isinstance(failure, Uncertain)
        return self.finish(Status.UNCERTAIN_RESOLVED if resolved else Status.FAILED, detail)

    def effect_visible(self, step: Step, refreshed: OrderState) -> bool:
        if step is Step.ADD_TAG:
            return self.job.plan.plan_tag in refreshed.tags
        pending = assess(refreshed, self.job.entry, self.job.plan, self.job.email, tagging=False)
        return pending.diverged is None and step not in pending.steps


def fetch_state(ctx: ApplyContext, entry: PlanEntry) -> OrderState | OrderOutcome:
    state = ctx.client.fetch_order(entry.order)
    if isinstance(state, OrderState):
        return state
    status = Status.REFUSED if isinstance(state, NotExecuted) else Status.FAILED
    return report(ctx, entry, status, describe(state))


def apply_order(ctx: ApplyContext, entry: PlanEntry) -> OrderOutcome:
    state = fetch_state(ctx, entry)
    if isinstance(state, OrderOutcome):
        return state
    job = Job(entry, ctx.plan, resolve_times(entry, ctx.clock()), ctx.email_secret)
    return OrderRun(ctx, job, state).run()
