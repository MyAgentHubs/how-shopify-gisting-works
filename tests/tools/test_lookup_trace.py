import json

from tool_support import (
    SECRET,
    SESSION,
    canary_for,
    email_for,
    everything_wire,
    harness,
    shipped_order,
)

from gisting.tools.trace import internal_json, public_json

PUBLIC_KEYS = {"tool", "order_number", "outcome"}
INTERNAL_KEYS = {
    "tool",
    "session_id",
    "order_number",
    "result_type",
    "cache_hit",
    "detail",
    "failures_before",
    "shopify_ms",
}


def test_public_projection_for_a_match_has_only_tool_order_and_outcome() -> None:
    response = harness(shipped_order(1042)).lookup("1042", email_for(1042))
    public = public_json(response.trace.public)
    assert set(public) == PUBLIC_KEYS
    assert public == {"tool": "lookup_order", "order_number": "#1042", "outcome": "completed"}


def test_match_and_no_match_look_the_same_in_the_public_projection() -> None:
    env = harness(shipped_order(1042))
    match = env.lookup("1042", email_for(1042))
    miss = env.lookup("1042", "wrong@example.com")
    assert public_json(match.trace.public) == public_json(miss.trace.public)


def test_canary_never_reaches_the_public_projection() -> None:
    env = harness(shipped_order(1042))
    response = env.lookup("1042", email_for(1042))
    assert canary_for(1042) in json.dumps(response.result)
    assert canary_for(1042) not in json.dumps(public_json(response.trace.public))
    assert canary_for(1042) not in json.dumps(internal_json(response.trace.internal))


def test_no_projection_contains_the_supplied_email_or_the_secret() -> None:
    env = harness(shipped_order(1042))
    for email in (email_for(1042), "someone@orders.example.com"):
        response = env.lookup("1042", email)
        for projection in (
            public_json(response.trace.public),
            internal_json(response.trace.internal),
        ):
            assert email not in json.dumps(projection)
            assert SECRET not in json.dumps(projection)
        assert SECRET not in everything_wire(response)


def test_internal_projection_keeps_the_typed_result() -> None:
    env = harness(shipped_order(1042))
    miss = env.lookup("1042", "wrong@example.com")
    internal = internal_json(miss.trace.internal)
    assert set(internal) == INTERNAL_KEYS
    assert internal["result_type"] == "Mismatch"
    assert internal["detail"] == "input_email"
    assert internal["cache_hit"] is None
    assert internal["session_id"] == SESSION
    found = env.lookup("1042", email_for(1042))
    assert found.trace.internal.result_type == "Found"
    assert found.trace.internal.cache_hit is False


def test_public_projection_has_no_timing_or_cache_fields() -> None:
    response = harness(shipped_order(1042)).lookup("1042", email_for(1042))
    wire = json.dumps(public_json(response.trace.public))
    assert "cache" not in wire
