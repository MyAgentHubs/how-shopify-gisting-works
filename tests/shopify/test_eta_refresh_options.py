from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from eta_refresh_support import NEW_ETA, read_calls, seeded
from fakes.shopify import FakeTransport, obj
from shipment_support import NOW, context, make_plan

from gisting.shopify.demo_config import load_config
from gisting.shopify.eta_refresh import RefreshOptions, RefreshRun, RefreshStatus
from gisting.shopify.plan import EventPlan, Offset, format_time


@pytest.mark.parametrize("days", [1, 7, 30])
@pytest.mark.parametrize("scenario", ["IN_TRANSIT", "OUT_FOR_DELIVERY"])
def test_chosen_horizon_is_written_and_verified(tmp_path: Path, days: int, scenario: str) -> None:
    planned, order = seeded(scenario=scenario)
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan(planned))
    outcome = RefreshRun(ctx, load_config(), planned, options=RefreshOptions(days)).run()
    expected = format_time(NOW + timedelta(days=days))
    assert outcome.result == RefreshStatus.WRITTEN
    assert outcome.new_eta == expected
    event = obj(fake.writes[0].variables["fulfillmentEvent"])
    assert event["estimatedDeliveryAt"] == expected
    assert event["happenedAt"] == format_time(NOW)
    assert event["status"] == scenario
    assert order.fulfillments[0].estimated_delivery_at == expected
    assert len(fake.writes) == 1
    assert read_calls(fake) == 2


@pytest.mark.parametrize("days", [None, 7])
def test_force_refreshes_fresh_eta(tmp_path: Path, days: int | None) -> None:
    planned, order = seeded()
    order.fulfillments[0].estimated_delivery_at = NEW_ETA
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan(planned))
    outcome = RefreshRun(ctx, load_config(), planned, options=RefreshOptions(days, True)).run()
    assert outcome.result == RefreshStatus.WRITTEN
    assert len(fake.writes) == 1
    assert read_calls(fake) == 2


def test_chosen_horizon_without_force_skips_fresh_eta(tmp_path: Path) -> None:
    planned, order = seeded()
    order.fulfillments[0].estimated_delivery_at = NEW_ETA
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan(planned))
    outcome = RefreshRun(ctx, load_config(), planned, options=RefreshOptions(7)).run()
    assert outcome.result == RefreshStatus.FRESH
    assert fake.writes == []


@pytest.mark.parametrize("days", [None, 7])
@pytest.mark.parametrize(
    "missing", ["delivered", "fulfillment", "event", "old_eta", "offset", "unknown_status"]
)
def test_force_and_horizon_preserve_no_eta_skip(
    tmp_path: Path, days: int | None, missing: str
) -> None:
    planned, order = seeded(scenario="DELIVERED" if missing == "delivered" else "IN_TRANSIT")
    if missing == "fulfillment":
        order.fulfillments.clear()
    elif missing == "event":
        order.fulfillments[0].events.clear()
    elif missing == "old_eta":
        order.fulfillments[0].estimated_delivery_at = None
    elif missing == "offset":
        planned = replace(planned, event=EventPlan("IN_TRANSIT", Offset(-1, 0), None))
    elif missing == "unknown_status":
        order.fulfillments[0].events[0]["status"] = "UNKNOWN"
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan(planned))
    outcome = RefreshRun(ctx, load_config(), planned, options=RefreshOptions(days, True)).run()
    assert outcome.result == RefreshStatus.NO_ETA
    assert fake.writes == []


@pytest.mark.parametrize("days", [None, 7])
def test_force_preserves_past_skip_unless_horizon_is_chosen(
    tmp_path: Path, days: int | None
) -> None:
    planned, order = seeded()
    planned = replace(planned, event=EventPlan("DELAYED", Offset(-1, 0), Offset(-2, 0)))
    order.fulfillments[0].events[0]["status"] = "DELAYED"
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan(planned))
    outcome = RefreshRun(ctx, load_config(), planned, options=RefreshOptions(days, True)).run()
    assert outcome.result == (RefreshStatus.PAST if days is None else RefreshStatus.WRITTEN)
    assert len(fake.writes) == (0 if days is None else 1)


def test_chosen_horizon_readback_mismatch_is_not_retried(tmp_path: Path) -> None:
    planned, order = seeded()
    order.fulfillments[0].update_eta = False
    fake = FakeTransport([order])
    ctx = context(tmp_path, fake, make_plan(planned))
    outcome = RefreshRun(ctx, load_config(), planned, options=RefreshOptions(7, True)).run()
    assert outcome.result == RefreshStatus.MISMATCH
    assert outcome.new_eta == format_time(NOW + timedelta(days=7))
    assert len(fake.writes) == 1
    assert read_calls(fake) == 2
