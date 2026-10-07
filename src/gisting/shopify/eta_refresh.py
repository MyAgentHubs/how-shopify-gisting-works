from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from gisting.shopify.apply_order import ApplyContext, describe
from gisting.shopify.apply_steps import Job, Times, step_variables
from gisting.shopify.assess import Step
from gisting.shopify.client import Verified
from gisting.shopify.demo_config import DistributionConfig
from gisting.shopify.jsonvalue import Json, JsonObject
from gisting.shopify.order_state import EventState, OrderState
from gisting.shopify.plan import EventPlan, Offset, PlanEntry, format_time, resolve_offset
from gisting.shopify.results import Failure, NotExecuted, Ok, Result, Uncertain
from gisting.shopify.run_plan import Pacing, paced


class RefreshStatus(StrEnum):
    WRITTEN = "written"
    WOULD_WRITE = "would_write"
    FRESH = "skipped_fresh"
    NO_ETA = "skipped_no_eta"
    PAST = "skipped_past_by_design"
    MISMATCH = "mismatch"
    UNCERTAIN = "uncertain"
    FAILED = "failed"
    REFUSED = "refused"


FAILURES = frozenset({
    RefreshStatus.MISMATCH,
    RefreshStatus.UNCERTAIN,
    RefreshStatus.FAILED,
    RefreshStatus.REFUSED,
})


@dataclass(frozen=True)
class RefreshOutcome:
    order: str
    result: RefreshStatus
    old_eta: str | None = None
    new_eta: str | None = None
    detail: str = ""

    def json(self) -> JsonObject:
        return {
            "order": self.order,
            "result": self.result.value,
            "old_eta": self.old_eta,
            "new_eta": self.new_eta,
            "detail": self.detail,
        }


def parse_time(raw: str) -> datetime:
    moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        message = "timestamp has no timezone"
        raise ValueError(message)
    return moment


def same_instant(actual: str | None, expected: str | None) -> bool:
    if actual is None or expected is None:
        return False
    try:
        return parse_time(actual) == parse_time(expected)
    except ValueError:
        return False


def current_event(state: OrderState) -> EventState | None:
    if not state.fulfillments or not state.fulfillments[0].events:
        return None
    return max(
        reversed(state.fulfillments[0].events),
        key=lambda event: (
            parse_time(event.happened_at) if event.happened_at else datetime.min.replace(tzinfo=UTC)
        ),
    )


def original_offset(entry: PlanEntry, status: str, config: DistributionConfig) -> Offset | None:
    if entry.event is not None and entry.event.status == status:
        return entry.event.estimated_delivery_at
    target = next(
        (event for event in config.set_state_events.values() if event.status == status), None
    )
    if target is None or target.eta_hours is None:
        return None
    return Offset.from_hours(target.eta_hours, target.same_day)


def read_failure_status(failure: Failure) -> RefreshStatus:
    if isinstance(failure, NotExecuted):
        return RefreshStatus.REFUSED
    return RefreshStatus.UNCERTAIN if isinstance(failure, Uncertain) else RefreshStatus.FAILED


@dataclass(frozen=True)
class RefreshOptions:
    eta_days: int | None = None
    force: bool = False


@dataclass
class RefreshRun:
    ctx: ApplyContext
    config: DistributionConfig
    entry: PlanEntry
    dry_run: bool = False
    old_eta: str | None = None
    new_eta: str | None = None
    options: RefreshOptions = RefreshOptions()

    def finish(self, status: RefreshStatus, detail: str = "") -> RefreshOutcome:
        outcome = RefreshOutcome(self.entry.order, status, self.old_eta, self.new_eta, detail)
        self.ctx.ledger.record({
            **outcome.json(),
            "kind": "refresh_eta_result",
            "at": format_time(self.ctx.clock()),
            "scenario": self.entry.scenario,
            "status": status.value,
            "canary": self.entry.canary,
            "estimated_delivery_at": self.new_eta,
        })
        return outcome

    def run(self) -> RefreshOutcome:
        state = self.ctx.client.fetch_order(self.entry.order)
        if not isinstance(state, OrderState):
            return self.finish(read_failure_status(state), describe(state))
        guard = self.ctx.client.writable(state)
        if isinstance(guard, NotExecuted):
            return self.finish(RefreshStatus.REFUSED, describe(guard))
        if self.entry not in self.ctx.plan.entries or self.ctx.plan.plan_tag not in state.tags:
            return self.finish(RefreshStatus.REFUSED, "missing plan entry or tag")
        try:
            prepared = self.prepare(state)
        except ValueError as error:
            return self.finish(RefreshStatus.FAILED, f"invalid timestamp: {error}")
        if isinstance(prepared, RefreshOutcome):
            return prepared
        return self.perform(state, guard, prepared)

    def perform(self, state: OrderState, guard: Verified, job: Job) -> RefreshOutcome:
        if self.dry_run:
            return self.finish(RefreshStatus.WOULD_WRITE)
        variables = step_variables(Step.CREATE_EVENT, state, job)
        self.ctx.ledger.record({
            "kind": "refresh_eta_intent",
            "at": format_time(self.ctx.clock()),
            "order": self.entry.order,
            "step": Step.CREATE_EVENT.value,
            "old_eta": self.old_eta,
            "estimated_delivery_at": self.new_eta,
            "happened_at": job.times.happened_at,
        })
        result = self.ctx.client.write(guard, Step.CREATE_EVENT.value, variables)
        return self.verify(result)

    def prepare(self, state: OrderState) -> Job | RefreshOutcome:
        event = current_event(state)
        self.old_eta = state.fulfillments[0].estimated_delivery_at if state.fulfillments else None
        offset = original_offset(self.entry, event.status, self.config) if event else None
        if self.old_eta is None or offset is None or event is None:
            return self.finish(RefreshStatus.NO_ETA)
        now = self.ctx.clock()
        grace = timedelta(minutes=self.config.stale_grace_minutes)
        if not self.options.force and parse_time(self.old_eta) >= now - grace:
            return self.finish(RefreshStatus.FRESH)
        return self.prepare_job(event, offset, now)

    def prepare_job(self, event: EventState, offset: Offset, now: datetime) -> Job | RefreshOutcome:
        target = (
            now + timedelta(days=self.options.eta_days)
            if self.options.eta_days is not None
            else resolve_offset(now, offset)
        )
        self.new_eta = format_time(target)
        if target < now:
            return self.finish(RefreshStatus.PAST)
        derived = replace(self.entry, event=EventPlan(event.status, Offset(0, 0), offset))
        return Job(
            derived, self.ctx.plan, Times(format_time(now), self.new_eta), self.ctx.email_secret
        )

    def verify(self, result: Result) -> RefreshOutcome:
        if isinstance(result, NotExecuted):
            return self.finish(RefreshStatus.FAILED, describe(result))
        refreshed = self.ctx.client.fetch_order(self.entry.order)
        if not isinstance(refreshed, OrderState):
            return self.finish(
                RefreshStatus.UNCERTAIN,
                f"effect_observed=unknown; verification read failed: {describe(refreshed)}",
            )
        observed = bool(refreshed.fulfillments) and same_instant(
            refreshed.fulfillments[0].estimated_delivery_at, self.new_eta
        )
        if isinstance(result, Ok):
            return self.finish(RefreshStatus.WRITTEN if observed else RefreshStatus.MISMATCH)
        status = RefreshStatus.UNCERTAIN if isinstance(result, Uncertain) else RefreshStatus.FAILED
        return self.finish(status, f"{describe(result)}; effect_observed={observed}")


@dataclass
class RefreshBatch:
    ctx: ApplyContext
    config: DistributionConfig
    dry_run: bool = False
    options: RefreshOptions = RefreshOptions()
    stopped: str | None = field(default=None, init=False)

    def run(
        self, entries: Sequence[PlanEntry], pacing: Pacing, max_failures: int
    ) -> list[RefreshOutcome]:
        self.stopped = None
        outcomes: list[RefreshOutcome] = []
        streak = 0
        for entry in paced(entries, pacing):
            outcome = RefreshRun(
                self.ctx, self.config, entry, self.dry_run, options=self.options
            ).run()
            outcomes.append(outcome)
            streak = streak + 1 if outcome.result in FAILURES else 0
            if outcome.result is RefreshStatus.UNCERTAIN:
                self.stopped = f"{entry.order}: {outcome.result.value}; outcome unresolved"
                break
            if streak >= max_failures:
                self.stopped = (
                    f"{entry.order}: {outcome.result.value}; {streak} consecutive failures"
                )
                break
        return outcomes


def refresh_json(outcomes: Sequence[RefreshOutcome]) -> JsonObject:
    summary: JsonObject = dict(Counter(outcome.result.value for outcome in outcomes))
    orders: list[Json] = [outcome.json() for outcome in outcomes]
    return {"summary": summary, "orders": orders}
