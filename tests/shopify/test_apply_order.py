import json
from pathlib import Path

from fakes.shopify import FakeOrder, FakeTransport
from shipment_support import NOTE_TEMPLATE, PLAN_TAG, SECRET, context, entry, fulfilled, make_plan

from gisting.shopify.apply_order import Status, apply_order
from gisting.shopify.demo_email import demo_email
from gisting.shopify.results import GraphQLError, Uncertain

NOTE_FOR_1002 = NOTE_TEMPLATE.format(canary="GLR-000003EA")


def names(fake: FakeTransport) -> list[str]:
    return [request.name for request in fake.writes]


def test_full_flow_for_in_transit_order(tmp_path: Path) -> None:
    order = FakeOrder(1002, quantity=2)
    fake = FakeTransport([order])
    planned = entry(1002, "IN_TRANSIT", quantity=2)
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.APPLIED
    assert names(fake) == [
        "order_update",
        "fulfillment_create",
        "fulfillment_event_create",
        "tags_add",
    ]
    assert order.note == NOTE_FOR_1002
    assert order.email == demo_email(SECRET, "#1002")
    assert PLAN_TAG in order.tags
    shipment = order.fulfillments[0]
    assert shipment.quantity == 2
    assert shipment.tracking[0]["number"] == "TP-0000001002"
    assert shipment.events[0]["status"] == "IN_TRANSIT"
    assert shipment.events[0]["happenedAt"] == "2026-10-01T10:00:00Z"
    assert shipment.estimated_delivery_at == "2026-10-04T10:00:00Z"
    assert order.status == "FULFILLED"


def test_customer_is_never_notified(tmp_path: Path) -> None:
    fake = FakeTransport([FakeOrder(1002)])
    planned = entry(1002, "IN_TRANSIT")
    apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    create = next(r for r in fake.writes if r.name == "fulfillment_create")
    assert create.variables["fulfillment"]["notifyCustomer"] is False  # type: ignore[index]


def test_unfulfilled_plan_only_updates_and_tags(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    fake = FakeTransport([order])
    planned = entry(1002, "UNFULFILLED")
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.APPLIED
    assert names(fake) == ["order_update", "tags_add"]
    assert order.status == "UNFULFILLED"


def test_partial_plan_ships_quantity_minus_one(tmp_path: Path) -> None:
    order = FakeOrder(1002, quantity=3)
    fake = FakeTransport([order])
    planned = entry(1002, "PARTIALLY_FULFILLED", quantity=3)
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.APPLIED
    assert order.fulfillments[0].quantity == 2
    assert order.status == "PARTIALLY_FULFILLED"


def test_no_tracking_plan_sends_neither_tracking_nor_event(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    fake = FakeTransport([order])
    planned = entry(1002, "FULFILLED_NO_TRACKING")
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.APPLIED
    assert names(fake) == ["order_update", "fulfillment_create", "tags_add"]
    assert order.fulfillments[0].tracking == []
    assert order.fulfillments[0].events == []


def test_tagged_order_is_skipped_without_writes(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    fake = FakeTransport([order])
    planned = entry(1002, "IN_TRANSIT")
    ctx = context(tmp_path, fake, make_plan(planned))
    assert apply_order(ctx, planned).status is Status.APPLIED
    writes_before = len(fake.writes)
    assert apply_order(ctx, planned).status is Status.SKIPPED_TAGGED
    assert len(fake.writes) == writes_before


def test_interrupted_order_resumes_without_second_fulfilment(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    planned = entry(1002, "IN_TRANSIT")
    fulfilled(order, planned)
    order.note = NOTE_FOR_1002
    order.email = demo_email(SECRET, "#1002")
    fake = FakeTransport([order])
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.APPLIED
    assert names(fake) == ["fulfillment_event_create", "tags_add"]
    assert len(order.fulfillments) == 1


def test_order_at_target_state_without_plan_tag_is_applied(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    fake = FakeTransport([order])
    planned = entry(1002, "IN_TRANSIT")
    ctx = context(tmp_path, fake, make_plan(planned))
    assert apply_order(ctx, planned).status is Status.APPLIED
    order.tags.remove(PLAN_TAG)
    before = len(fake.writes)
    outcome = apply_order(ctx, planned)
    assert outcome.status is Status.APPLIED
    assert outcome.steps == ("tags_add",)
    assert names(fake)[before:] == ["tags_add"]
    assert PLAN_TAG in order.tags


def test_shipped_order_cannot_be_planned_as_unfulfilled(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    fulfilled(order, entry(1002, "IN_TRANSIT"))
    fake = FakeTransport([order])
    planned = entry(1002, "UNFULFILLED")
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.DIVERGED
    assert "未发货" in outcome.detail
    assert fake.writes == []


def test_non_test_order_is_refused_without_writes(tmp_path: Path) -> None:
    fake = FakeTransport([FakeOrder(1002, test=False)])
    planned = entry(1002, "IN_TRANSIT")
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.REFUSED
    assert fake.writes == []


def test_order_without_batch_tag_is_refused(tmp_path: Path) -> None:
    fake = FakeTransport([FakeOrder(1002, tags=[])])
    planned = entry(1002, "IN_TRANSIT")
    assert (
        apply_order(context(tmp_path, fake, make_plan(planned)), planned).status is Status.REFUSED
    )
    assert fake.writes == []


def test_missing_order_is_refused(tmp_path: Path) -> None:
    fake = FakeTransport([])
    planned = entry(1002, "IN_TRANSIT")
    assert (
        apply_order(context(tmp_path, fake, make_plan(planned)), planned).status is Status.REFUSED
    )


def test_uncertain_write_that_took_effect_stops_the_order_without_retry(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    fake = FakeTransport([order])
    fake.fail("fulfillment_create", Uncertain("tls"), applied=True)
    planned = entry(1002, "IN_TRANSIT")
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.UNCERTAIN_RESOLVED
    assert "effect_observed=True" in outcome.detail
    assert names(fake) == ["order_update", "fulfillment_create"]
    assert PLAN_TAG not in order.tags


def test_uncertain_write_that_did_not_take_effect_is_recorded(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    fake = FakeTransport([order])
    fake.fail("fulfillment_create", Uncertain("tls"), applied=False)
    planned = entry(1002, "IN_TRANSIT")
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.UNCERTAIN_RESOLVED
    assert "effect_observed=False" in outcome.detail
    assert order.fulfillments == []


def test_rerun_after_uncertain_completes_without_duplicate_fulfilment(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    fake = FakeTransport([order])
    fake.fail("fulfillment_create", Uncertain("tls"), applied=True)
    planned = entry(1002, "IN_TRANSIT")
    ctx = context(tmp_path, fake, make_plan(planned))
    assert apply_order(ctx, planned).status is Status.UNCERTAIN_RESOLVED
    assert apply_order(ctx, planned).status is Status.APPLIED
    assert len(order.fulfillments) == 1
    assert names(fake).count("fulfillment_create") == 1


def test_uncertain_write_with_failing_verification_is_unresolved(tmp_path: Path) -> None:
    fake = FakeTransport([FakeOrder(1002)])
    fake.fail("fulfillment_create", Uncertain("tls"), applied=True)
    fake.fail("order_state", Uncertain("tls"), skip=2)
    fake.fail("order_state", Uncertain("tls"))
    fake.fail("order_state", Uncertain("tls"))
    planned = entry(1002, "IN_TRANSIT")
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.UNCERTAIN
    assert names(fake) == ["order_update", "fulfillment_create"]


def test_graphql_error_on_write_is_failure_not_uncertain(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    fake = FakeTransport([order])
    fake.fail("order_update", GraphQLError(({"message": "denied"},)))
    planned = entry(1002, "IN_TRANSIT")
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.FAILED
    assert "denied" in outcome.detail
    assert names(fake) == ["order_update"]


def test_ledger_records_intent_and_one_result_per_order(tmp_path: Path) -> None:
    fake = FakeTransport([FakeOrder(1002)])
    planned = entry(1002, "IN_TRANSIT")
    ctx = context(tmp_path, fake, make_plan(planned))
    apply_order(ctx, planned)
    lines = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    kinds = [line["kind"] for line in lines]
    assert kinds.count("result") == 1
    assert kinds.count("intent") == 4
    result = next(line for line in lines if line["kind"] == "result")
    assert result["status"] == "applied"
    assert result["order"] == "#1002"
    assert "@" not in json.dumps(lines)


def test_note_keeps_dev_store_provenance_and_canary() -> None:
    note = NOTE_FOR_1002
    assert "Test order for Gisting Lab experiments in a Shopify development store." in note
    assert note.endswith("Reference GLR-000003EA")


def test_email_readback_matching_is_recorded_as_applied(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    fake = FakeTransport([order])
    planned = entry(1002, "UNFULFILLED")
    assert (
        apply_order(context(tmp_path, fake, make_plan(planned)), planned).status is Status.APPLIED
    )
    assert order.email == demo_email(SECRET, "#1002")


def test_email_readback_missing_fails_without_retry_or_further_writes(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    order.email_write = "drop"
    fake = FakeTransport([order])
    planned = entry(1002, "IN_TRANSIT")
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.FAILED
    assert outcome.detail == "email 回读 missing"
    assert names(fake) == ["order_update"]
    assert PLAN_TAG not in order.tags
    assert "@" not in (tmp_path / "ledger.jsonl").read_text()


def test_email_readback_mismatch_fails_without_retry_or_further_writes(tmp_path: Path) -> None:
    order = FakeOrder(1002)
    order.email_write = "alter"
    fake = FakeTransport([order])
    planned = entry(1002, "IN_TRANSIT")
    outcome = apply_order(context(tmp_path, fake, make_plan(planned)), planned)
    assert outcome.status is Status.FAILED
    assert outcome.detail == "email 回读 mismatch"
    assert names(fake) == ["order_update"]
    assert "@" not in (tmp_path / "ledger.jsonl").read_text()
