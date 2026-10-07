from typing import Any

import pytest
from replies_support import detailed, field, found

from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import Unrenderable, UnrenderableReply, fixed_reply, render_reply

PHRASES = load_phrases()
UNKNOWN = ["CANCELED", "LABEL_PRINTED", "FAILURE", "NOT_DELIVERED", "READY_FOR_PICKUP", "", " "]


def with_status(status: object) -> dict[str, object]:
    node = detailed("IN_TRANSIT")
    node["transport_status"] = {"value": status, "source": "shopify"}
    return node


@pytest.mark.parametrize("status", [*UNKNOWN, None, 7])
def test_a_single_parcel_of_an_unknown_status_is_not_rendered(status: object) -> None:
    result = render_reply(PHRASES, found("FULFILLED", with_status(status)))
    assert isinstance(result, Unrenderable)
    assert result.reason.startswith("transport_status:")


@pytest.mark.parametrize("status", UNKNOWN)
@pytest.mark.parametrize("position", [0, 1, 2])
def test_one_unknown_parcel_among_several_makes_the_whole_order_unrenderable(
    status: str, position: int
) -> None:
    parcels = [detailed("IN_TRANSIT"), detailed("DELAYED"), detailed("DELIVERED")]
    parcels[position] = with_status(status)
    for fulfillment in ("FULFILLED", "PARTIALLY_FULFILLED"):
        assert isinstance(render_reply(PHRASES, found(fulfillment, *parcels)), Unrenderable)


def test_an_unknown_parcel_beats_the_several_parcels_reply() -> None:
    parcels = [detailed("IN_TRANSIT")] * 4
    assert render_reply(PHRASES, found("FULFILLED", *parcels)) == PHRASES.parcels.many_reply
    result = render_reply(PHRASES, found("FULFILLED", *parcels[:3], with_status("CANCELED")))
    assert isinstance(result, Unrenderable)


@pytest.mark.parametrize("fulfillment", ["ON_HOLD", "IN_PROGRESS", "RESTOCKED", "", "fulfilled"])
def test_an_order_status_without_copy_is_not_rendered(fulfillment: str) -> None:
    for parcels in ([], [detailed("IN_TRANSIT")], [detailed("IN_TRANSIT")] * 2):
        result = render_reply(PHRASES, found(fulfillment, *parcels))
        assert isinstance(result, Unrenderable)
        assert result.reason == f"fulfillment_status:{fulfillment or None}"


def test_an_order_with_no_status_at_all_is_not_rendered() -> None:
    assert isinstance(render_reply(PHRASES, {"status": "found", "order": {}}), Unrenderable)
    assert isinstance(render_reply(PHRASES, {"status": "found"}), Unrenderable)
    order: dict[str, Any] = {"fulfillment_status": field(None), "shipments": []}
    assert isinstance(render_reply(PHRASES, {"status": "found", "order": order}), Unrenderable)


def test_a_shipped_order_with_no_parcel_is_not_rendered() -> None:
    result = render_reply(PHRASES, found("FULFILLED"))
    assert result == Unrenderable("no_shipments:FULFILLED")


def test_an_unshipped_order_does_not_need_its_parcels_to_be_readable() -> None:
    reply = render_reply(PHRASES, found("UNFULFILLED", with_status("CANCELED")))
    assert reply == fixed_reply(PHRASES, found("UNFULFILLED"))
    assert isinstance(reply, str)


def test_a_partly_shipped_order_with_no_parcel_still_gets_its_approved_line() -> None:
    reply = render_reply(PHRASES, found("PARTIALLY_FULFILLED"))
    assert reply == (
        f"Your order has partly shipped. {PHRASES.no_shipment_details} "
        f"{PHRASES.sentences['unshipped_rest']}"
    )


def test_an_unknown_result_status_is_not_rendered() -> None:
    assert render_reply(PHRASES, {"status": "needs_customer_input"}) == Unrenderable(
        "result_status:needs_customer_input"
    )
    assert render_reply(PHRASES, {}) == Unrenderable("result_status:None")


def test_the_string_helper_raises_the_typed_error_instead_of_returning_a_made_up_line() -> None:
    with pytest.raises(UnrenderableReply, match="transport_status:CANCELED"):
        fixed_reply(PHRASES, found("FULFILLED", with_status("CANCELED")))
