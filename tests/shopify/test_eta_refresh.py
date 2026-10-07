import json
from dataclasses import replace
from pathlib import Path

import pytest
from eta_refresh_support import NEW_ETA, OLD_ETA, read_calls, seeded
from fakes.shopify import FakeTransport, items, obj
from shipment_support import NOW, PLAN_TAG, context, make_plan

from gisting.shopify.demo_config import load_config
from gisting.shopify.eta_refresh import RefreshBatch, RefreshRun, RefreshStatus
from gisting.shopify.plan import EventPlan, Offset
from gisting.shopify.results import Cause, GraphQLError, NotExecuted, Ok, Uncertain
from gisting.shopify.run_plan import Pacing
from gisting.shopify.transport import Request


def test_stale_appends_one_event_and_verifies_eta(tmp_path: Path) -> None:
    planned, order = seeded()
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan(planned))
    outcome = RefreshRun(ctx, load_config(), planned).run()
    assert outcome.result == RefreshStatus.WRITTEN
    assert (outcome.old_eta, outcome.new_eta) == (OLD_ETA, NEW_ETA)
    assert len(fake.writes) == 1
    assert fake.writes[0].name == "fulfillment_event_create"
    assert fake.writes[0].variables == {
        "fulfillmentEvent": {
            "fulfillmentId": order.fulfillments[0].id,
            "status": "IN_TRANSIT",
            "happenedAt": "2026-10-02T10:00:00Z",
            "estimatedDeliveryAt": NEW_ETA,
        }
    }
    assert read_calls(fake) == 2
    records = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert [record["kind"] for record in records] == ["refresh_eta_intent", "refresh_eta_result"]
    assert records[-1]["status"] == "written"
    assert RefreshRun(ctx, load_config(), planned).run().result == RefreshStatus.FRESH
    assert len(fake.writes) == 1


@pytest.mark.parametrize("eta", [NEW_ETA, "2026-10-02T10:00:00Z"])
def test_fresh_including_boundary_never_writes(tmp_path: Path, eta: str) -> None:
    planned, order = seeded()
    order.fulfillments[0].estimated_delivery_at = eta
    fake = FakeTransport([order])
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == RefreshStatus.FRESH
    assert fake.writes == []


@pytest.mark.parametrize("case", ["delivered", "no_fulfillment", "no_events", "unknown_status"])
def test_missing_eta_semantics_skips(tmp_path: Path, case: str) -> None:
    planned, order = seeded(scenario="DELIVERED" if case == "delivered" else "IN_TRANSIT")
    if case == "no_fulfillment":
        order.fulfillments.clear()
    elif case == "no_events":
        order.fulfillments[0].events.clear()
    elif case == "unknown_status":
        order.fulfillments[0].events[0]["status"] = "UNKNOWN"
    fake = FakeTransport([order])
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == RefreshStatus.NO_ETA
    assert fake.writes == []


def test_readback_mismatch_is_not_retried(tmp_path: Path) -> None:
    planned, order = seeded()
    order.fulfillments[0].update_eta = False
    fake = FakeTransport([order])
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == RefreshStatus.MISMATCH
    assert len(fake.writes) == 1
    assert read_calls(fake) == 2


@pytest.mark.parametrize("reason", ["not_test", "wrong_store", "missing_tag", "missing_batch"])
def test_unsafe_orders_are_refused(tmp_path: Path, reason: str) -> None:
    planned, order = seeded()
    if reason == "not_test":
        order.test = False
    elif reason == "missing_tag":
        order.tags.remove(PLAN_TAG)
    elif reason == "missing_batch":
        order.tags = [PLAN_TAG]
    fake = FakeTransport(
        [order],
        shop_domain="other.myshopify.com"
        if reason == "wrong_store"
        else "gisting-lab.myshopify.com",
    )
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == RefreshStatus.REFUSED
    assert fake.writes == []


def test_negative_offset_skips_past_by_design(tmp_path: Path) -> None:
    planned, order = seeded()
    planned = replace(planned, event=EventPlan("DELAYED", Offset(-1, 0), Offset(-2, 0)))
    order.fulfillments[0].events[0]["status"] = "DELAYED"
    fake = FakeTransport([order])
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == RefreshStatus.PAST
    assert fake.writes == []


def test_latest_event_wins_and_ties_choose_last_with_fallback_offset(tmp_path: Path) -> None:
    planned, order = seeded()
    order.fulfillments[0].events = [
        {"status": "DELAYED", "happenedAt": "2026-10-01T09:00:00Z"},
        {"status": "OUT_FOR_DELIVERY", "happenedAt": "2026-10-01T09:00:00Z"},
        {"status": "DELIVERED", "happenedAt": "2026-09-30T09:00:00Z"},
    ]
    fake = FakeTransport([order])
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == RefreshStatus.WRITTEN
    assert outcome.new_eta == "2026-10-02T13:00:00Z"
    assert obj(fake.writes[0].variables["fulfillmentEvent"])["status"] == "OUT_FOR_DELIVERY"


@pytest.mark.parametrize("applied", [True, False])
@pytest.mark.parametrize(
    "failure", [Uncertain("lost response"), GraphQLError(({"message": "bad"},))]
)
def test_ambiguous_or_graphql_failure_reads_once_and_never_retries(
    tmp_path: Path, applied: bool, failure: Uncertain | GraphQLError
) -> None:
    planned, order = seeded()
    fake = FakeTransport([order])
    fake.fail("fulfillment_event_create", failure, applied=applied)
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    expected = RefreshStatus.UNCERTAIN if isinstance(failure, Uncertain) else RefreshStatus.FAILED
    assert outcome.result == expected
    assert f"effect_observed={applied}" in outcome.detail
    assert len(fake.writes) == 1
    assert read_calls(fake) == 2


def test_verification_read_failure_is_uncertain(tmp_path: Path) -> None:
    planned, order = seeded()
    fake = FakeTransport([order])
    fake.fail("order_state", GraphQLError(({"message": "unavailable"},)), skip=1)
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == RefreshStatus.UNCERTAIN
    assert len(fake.writes) == 1
    assert read_calls(fake) == 2


def test_definite_write_failure_does_not_retry(tmp_path: Path) -> None:
    planned, order = seeded()
    fake = FakeTransport([order])
    fake.fail("fulfillment_event_create", NotExecuted(Cause.AUTH))
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == RefreshStatus.FAILED
    assert len(fake.writes) == 1


def test_grace_is_loaded_from_config_and_used(tmp_path: Path) -> None:
    planned, order = seeded()
    order.fulfillments[0].estimated_delivery_at = "2026-10-02T09:59:00Z"
    fake = FakeTransport([order])
    config = replace(load_config(), stale_grace_minutes=2)
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), config, planned).run()
    assert outcome.result == RefreshStatus.FRESH
    assert fake.writes == []


@pytest.mark.parametrize("uncertain", [True, False])
def test_batch_stops_on_uncertain_or_consecutive_failures(tmp_path: Path, uncertain: bool) -> None:
    pairs = [seeded(number) for number in (1006, 1014, 1020)]
    entries = [pair[0] for pair in pairs]
    fake = FakeTransport([pair[1] for pair in pairs])
    for _ in entries:
        fake.fail(
            "fulfillment_event_create", Uncertain("lost") if uncertain else NotExecuted(Cause.AUTH)
        )
    ctx = context(tmp_path, fake, make_plan(*entries))
    outcomes = RefreshBatch(ctx, load_config()).run(entries, Pacing(sleep=lambda _: None), 2)
    assert len(outcomes) == (1 if uncertain else 2)
    assert len(fake.writes) == len(outcomes)
    assert ctx.clock() == NOW


@pytest.mark.parametrize("missing", [False, True])
def test_plan_offset_has_priority_over_state_config(tmp_path: Path, missing: bool) -> None:
    planned, order = seeded()
    planned = replace(
        planned, event=EventPlan("IN_TRANSIT", Offset(-1, 0), None if missing else Offset(1, 3))
    )
    fake = FakeTransport([order])
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == (RefreshStatus.NO_ETA if missing else RefreshStatus.WRITTEN)
    assert outcome.new_eta == (None if missing else "2026-10-03T13:00:00Z")


def test_same_day_offset_caps_at_end_of_day(tmp_path: Path) -> None:
    planned, order = seeded(scenario="OUT_FOR_DELIVERY")
    fake = FakeTransport([order])
    ctx = replace(context(tmp_path, fake, make_plan(planned)), clock=lambda: NOW.replace(hour=23))
    outcome = RefreshRun(ctx, load_config(), planned).run()
    assert outcome.result == RefreshStatus.WRITTEN
    assert outcome.new_eta == "2026-10-02T23:59:00Z"


def test_failure_streak_resets_after_fresh_skip(tmp_path: Path) -> None:
    pairs = [seeded(number) for number in (1006, 1014, 1020)]
    entries = [pair[0] for pair in pairs]
    pairs[1][1].fulfillments[0].estimated_delivery_at = NEW_ETA
    fake = FakeTransport([pair[1] for pair in pairs])
    for _ in range(2):
        fake.fail("fulfillment_event_create", NotExecuted(Cause.AUTH))
    ctx = context(tmp_path, fake, make_plan(*entries))
    outcomes = RefreshBatch(ctx, load_config()).run(entries, Pacing(sleep=lambda _: None), 2)
    assert [outcome.result for outcome in outcomes] == [
        RefreshStatus.FAILED,
        RefreshStatus.FRESH,
        RefreshStatus.FAILED,
    ]


@pytest.mark.parametrize("uncertain", [False, True])
def test_initial_read_failure_never_writes(tmp_path: Path, uncertain: bool) -> None:
    planned, order = seeded()
    fake = FakeTransport([order])
    failure = Uncertain("read failed") if uncertain else GraphQLError(({"message": "bad"},))
    for _ in range(3 if uncertain else 1):
        fake.fail("order_state", failure)
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == (RefreshStatus.UNCERTAIN if uncertain else RefreshStatus.FAILED)
    assert fake.writes == []


def test_entry_outside_context_plan_is_refused(tmp_path: Path) -> None:
    planned, order = seeded()
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan())
    outcome = RefreshRun(ctx, load_config(), planned).run()
    assert outcome.result == RefreshStatus.REFUSED
    assert fake.writes == []


@pytest.mark.parametrize(
    ("readback", "expected"),
    [
        ("2026-10-04T10:00:00+00:00", RefreshStatus.WRITTEN),
        ("2026-10-04T10:00:00.000Z", RefreshStatus.WRITTEN),
        ("2026-10-04T12:00:00+02:00", RefreshStatus.WRITTEN),
        ("not-a-timestamp", RefreshStatus.MISMATCH),
        ("2026-10-04T10:00:00", RefreshStatus.MISMATCH),
        (None, RefreshStatus.MISMATCH),
        ("2026-10-04T10:00:00.001Z", RefreshStatus.MISMATCH),
    ],
)
def test_verification_compares_parsed_instants(
    tmp_path: Path, readback: str | None, expected: RefreshStatus
) -> None:
    planned, order = seeded()
    fake = FakeTransport([order])
    response = fake.execute(Request("order_state", "", {"query": "name:#1006"}))
    assert isinstance(response, Ok)
    node = obj(items(obj(response.data["orders"])["nodes"])[0])
    obj(items(node["fulfillments"])[0])["estimatedDeliveryAt"] = readback
    fake.calls.clear()
    fake.fail("order_state", response, skip=1)
    outcome = RefreshRun(context(tmp_path, fake, make_plan(planned)), load_config(), planned).run()
    assert outcome.result == expected
    assert outcome.new_eta == NEW_ETA
    assert len(fake.writes) == 1
    assert read_calls(fake) == 2
