import json
from typing import Any

from runner_support import (
    GOOD_EMAIL,
    NUMBER,
    WRONG_EMAIL,
    RigTurn,
    asking,
    lookup_call,
)
from serve_http import SECRET, started
from serve_support import INTERNAL_CANARY, Call, FakeTurn, record_read, traces

from gisting.agent.trace import Traces
from gisting.tools.reads import LookupRead

ORDER = f"#{NUMBER}"
SESSION = "lookup-session-3318"
LOOKUP_KEYS = {"shopify_ms", "result_type", "cache_hit"}
FRESH = LookupRead(312.4, "Found", False)
SECRETS = (ORDER, GOOD_EMAIL, WRONG_EMAIL, SESSION, INTERNAL_CANARY, SECRET)


def one_read(call: Call) -> None:
    record_read(call.reads, FRESH)


def two_reads(call: Call) -> None:
    record_read(call.reads, FRESH)
    record_read(call.reads, LookupRead(None, "NotFound", True))


def internal_claiming_a_read() -> dict[str, object]:
    trace = {"result_type": "Found", "cache_hit": False, "shopify_ms": 99.0}
    return {"reply_source": "code", "tool_calls": [{"name": "lookup_order", "trace": trace}]}


def generate_records(log: str) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in log.splitlines()]
    return [record for record in records if record["event"] == "generate"]


def test_the_generate_log_line_carries_the_lookup_reads_and_nothing_identifying() -> None:
    with started(FakeTurn(["done"], act=one_read)) as app:
        app.generate({"session_id": SESSION, "message": "hi", "mode": "gist"})
        log = app.log.getvalue()
    (record,) = generate_records(log)
    assert record["lookups"] == [{"shopify_ms": 312.4, "result_type": "Found", "cache_hit": False}]
    assert set(record["lookups"][0]) == LOOKUP_KEYS
    for secret in SECRETS:
        assert secret not in log


def test_two_lookups_in_one_turn_are_logged_in_order() -> None:
    with started(FakeTurn(["done"], act=two_reads)) as app:
        app.generate({"session_id": SESSION, "message": "hi", "mode": "gist"})
        (record,) = generate_records(app.log.getvalue())
    assert [read["result_type"] for read in record["lookups"]] == ["Found", "NotFound"]


def test_the_log_takes_reads_from_the_sink_and_never_from_the_internal_trace() -> None:
    claiming = Traces(traces().public, internal_claiming_a_read())
    with started(FakeTurn(["done"], result_traces=claiming)) as app:
        app.generate({"session_id": SESSION, "message": "hi", "mode": "gist"})
        (record,) = generate_records(app.log.getvalue())
    assert "lookups" not in record


def test_a_turn_without_lookups_logs_no_lookups_key() -> None:
    with started(FakeTurn(["hello"])) as app:
        app.generate({"session_id": SESSION, "message": "hi", "mode": "gist"})
        log = app.log.getvalue()
    (record,) = generate_records(log)
    assert "lookups" not in record


def test_the_response_never_carries_the_lookup_reads() -> None:
    with started(FakeTurn(["done"], act=one_read)) as app:
        reply = app.generate({"session_id": SESSION, "message": "hi", "mode": "gist"})
    body = reply.body.decode()
    headers = json.dumps(reply.headers)
    for needle in ("shopify_ms", "lookups", "cache_hit", "312.4"):
        assert needle not in body
        assert needle not in headers


def test_real_lookups_through_the_runner_are_logged_per_request() -> None:
    turn = RigTurn()
    for email in (GOOD_EMAIL, GOOD_EMAIL, WRONG_EMAIL):
        turn.rig.gist_model.outputs.append(lookup_call(email))
    with started(turn) as app:
        for email in (GOOD_EMAIL, GOOD_EMAIL, WRONG_EMAIL):
            text = asking(email)[0].content
            reply = app.generate({"session_id": SESSION, "message": text, "mode": "gist"})
            assert reply.status == 200
        log = app.log.getvalue()
    first, second, third = (record["lookups"] for record in generate_records(log))
    assert first[0]["result_type"] == "Found"
    assert first[0]["cache_hit"] is False
    assert isinstance(first[0]["shopify_ms"], float)
    assert first[0]["shopify_ms"] >= 0
    assert second == [{"shopify_ms": None, "result_type": "Found", "cache_hit": True}]
    assert third == [{"shopify_ms": None, "result_type": "Mismatch", "cache_hit": None}]
    for secret in (*SECRETS, "canary", "GLR-"):
        assert secret not in log
