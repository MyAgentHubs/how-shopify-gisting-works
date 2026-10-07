import re
from dataclasses import dataclass
from typing import Any

from hypothesis import example, given, settings
from hypothesis import strategies as st
from replies_support import field

from gisting.prompt.phrases import load_phrases
from gisting.prompt.replies import Unrenderable, render_reply

PHRASES = load_phrases()
KNOWN = tuple(PHRASES.transport_status)
UNKNOWN = ("CANCELED", "LABEL_PRINTED", "FAILURE", "NOT_DELIVERED", "")
FULFILLMENTS = ("FULFILLED", "PARTIALLY_FULFILLED", "UNFULFILLED", "ON_HOLD", None)
STAMP_FORMS = (
    "2026-10-{day:02d}T10:00:00Z",
    "2026-10-{day:02d}T10:00:00.000Z",
    "2026-10-{day:02d}T10:00:00+00:00",
    "2026-10-{day:02d}",
)
YEAR = re.compile(r"\b(?:19|20)\d\d\b")


@dataclass(frozen=True)
class Stamp:
    text: str | None
    day: int | None


@dataclass(frozen=True)
class Parcel:
    status: str
    carrier: str | None
    tracking: str | None
    estimated: Stamp
    delivered: Stamp

    def node(self) -> dict[str, Any]:
        return {
            "transport_status": field(self.status),
            "carrier": field(self.carrier),
            "tracking_number": field(self.tracking),
            "estimated_delivery": field(self.estimated.text),
            "delivered_at": field(self.delivered.text),
        }

    def years(self) -> set[str]:
        return set(YEAR.findall(f"{self.carrier or ''} {self.tracking or ''}"))

    def numbers(self) -> set[str]:
        days = {str(stamp.day) for stamp in (self.estimated, self.delivered) if stamp.day}
        return days | set(re.findall(r"\d+", f"{self.carrier or ''} {self.tracking or ''}"))


def dated(form: str, day: int) -> Stamp:
    return Stamp(form.format(day=day), day)


stamps = st.one_of(
    st.just(Stamp(None, None)),
    st.builds(Stamp, st.sampled_from(["soon", "2026-13-45", ""]), st.none()),
    st.builds(dated, st.sampled_from(STAMP_FORMS), st.integers(min_value=1, max_value=28)),
)
parcels = st.builds(
    Parcel,
    st.sampled_from([*KNOWN, *UNKNOWN]),
    st.one_of(st.none(), st.sampled_from(["Test Parcel", "Australia Post Express", "DHL 5"])),
    st.one_of(st.none(), st.from_regex(r"TP-[0-9]{1,8}", fullmatch=True)),
    stamps,
    stamps,
)
TP_2000 = Parcel("DELIVERED", "Test Parcel", "TP-2000", Stamp(None, None), Stamp(None, None))
fulfillments = st.sampled_from(FULFILLMENTS)
orders = st.lists(parcels, max_size=6)


def result_of(fulfillment: str | None, items: list[Parcel]) -> dict[str, Any]:
    order = {"fulfillment_status": field(fulfillment), "shipments": [p.node() for p in items]}
    return {"status": "found", "order": order}


@settings(max_examples=400, deadline=None)
@given(fulfillments, orders)
@example("FULFILLED", [TP_2000])
def test_rendering_never_raises_and_says_nothing_that_is_not_in_the_input(
    fulfillment: str | None, items: list[Parcel]
) -> None:
    reply = render_reply(PHRASES, result_of(fulfillment, items))
    if isinstance(reply, Unrenderable):
        return
    assert "<" not in reply and ">" not in reply
    assert set(YEAR.findall(reply)) <= set().union(*(p.years() for p in items))
    assert set(re.findall(r"\d+", reply)) <= set().union(*(p.numbers() for p in items))


@settings(max_examples=400, deadline=None)
@given(fulfillments, orders)
def test_an_unknown_status_anywhere_makes_a_shipped_or_partly_shipped_order_unrenderable(
    fulfillment: str | None, items: list[Parcel]
) -> None:
    reply = render_reply(PHRASES, result_of(fulfillment, items))
    unknown_order = fulfillment not in PHRASES.fulfillment_status
    unknown_parcel = any(p.status not in KNOWN for p in items)
    expected = (
        unknown_order
        or (fulfillment != "UNFULFILLED" and unknown_parcel)
        or (fulfillment == "FULFILLED" and not items)
    )
    assert isinstance(reply, Unrenderable) is expected


def test_a_tracking_number_that_looks_like_a_year_renders() -> None:
    reply = render_reply(PHRASES, result_of("FULFILLED", [TP_2000]))
    assert not isinstance(reply, Unrenderable)
    assert "TP-2000" in reply
