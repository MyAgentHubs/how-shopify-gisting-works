import contextlib
import json
import socket
import threading
import time
from typing import cast

import pytest
from serve_http import GOOD_SESSION, JSON_HEADERS, SECRET, Reply, limited, quick_limits, started
from serve_support import INTERNAL_CANARY, PATIENCE, PUBLIC_TRACE, FakeTurn

from gisting.agent.trace import Traces
from gisting.serve.app import SECRET_HEADER
from gisting.serve.config import LIMITS

GOOD = {"session_id": GOOD_SESSION, "message": "where is my order", "mode": "gist"}


def error_type(reply: Reply) -> str:
    error = cast(dict[str, object], reply.json()["error"])
    return str(error["type"])


def test_generate_answers_with_the_answer_and_the_public_trace_only() -> None:
    turn = FakeTurn(["it ships soon"])
    turn.result_traces = Traces(
        {**PUBLIC_TRACE, "internal": INTERNAL_CANARY}, turn.result_traces.internal
    )
    with started(turn) as app:
        reply = app.generate(GOOD)
    assert reply.status == 200
    assert reply.json() == {"answer": "it ships soon", "trace": PUBLIC_TRACE}
    assert INTERNAL_CANARY.encode() not in reply.body
    assert reply.headers["content-type"] == "application/json; charset=utf-8"
    assert reply.headers["connection"] == "close"
    assert reply.headers["cache-control"] == "no-store"


def test_the_server_listens_on_loopback_only() -> None:
    with started() as app:
        assert app.server.server_address[0] == "127.0.0.1"


def test_health_reports_readiness_with_the_matching_status() -> None:
    with started() as app:
        reply = app.call("GET", "/health", headers={SECRET_HEADER: SECRET})
        assert reply.status == 200
        assert reply.json() == {"status": "ready", "running": 0, "waiting": 0}
    with started(ready=False) as app:
        reply = app.call("GET", "/health", headers={SECRET_HEADER: SECRET})
        assert reply.status == 503
        assert reply.json() == {"status": "loading", "running": 0, "waiting": 0}


def test_requests_while_loading_are_not_ready_with_a_retry_hint() -> None:
    turn = FakeTurn()
    with started(turn, ready=False) as app:
        reply = app.generate(GOOD)
    assert reply.status == 503
    assert error_type(reply) == "not_ready"
    assert reply.headers["retry-after"] == str(LIMITS.retry_after_s)
    assert turn.calls == []


@pytest.mark.parametrize("path", ["/health", "/generate", "/nowhere"])
@pytest.mark.parametrize(
    "headers",
    [{}, {SECRET_HEADER: "wrong-secret"}, {SECRET_HEADER: SECRET[:-1]}, {SECRET_HEADER: ""}],
)
def test_without_the_secret_every_route_is_unauthorized(path: str, headers: dict[str, str]) -> None:
    turn = FakeTurn()
    with started(turn) as app:
        reply = app.call("POST" if path == "/generate" else "GET", path, b"{}", headers)
    assert reply.status == 401
    assert error_type(reply) == "unauthorized"
    assert turn.calls == []


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1", "localhost:1", "127.0.0.1:1"])
def test_a_wrong_host_header_is_unauthorized_even_with_the_secret(host: str) -> None:
    turn = FakeTurn()
    with started(turn) as app:
        reply = app.call("GET", "/health", headers={SECRET_HEADER: SECRET, "Host": host})
        assert reply.status == 401
        reply = app.generate(GOOD, {**JSON_HEADERS, "Host": host})
    assert reply.status == 401
    assert turn.calls == []


def test_unauthorized_replies_are_identical_for_a_missing_and_a_wrong_secret() -> None:
    with started() as app:
        missing = app.call("GET", "/health")
        wrong = app.call("GET", "/health", headers={SECRET_HEADER: "nope"})
    assert (missing.status, missing.body) == (wrong.status, wrong.body)


def test_unknown_routes_and_methods_are_not_found_once_authorized() -> None:
    headers = {SECRET_HEADER: SECRET}
    with started() as app:
        assert app.call("GET", "/nowhere", headers=headers).status == 404
        assert app.call("GET", "/generate", headers=headers).status == 404
        assert app.call("POST", "/health", b"{}", headers).status == 404
        assert app.call("PUT", "/generate", b"{}", headers).status == 404
        assert app.call("DELETE", "/health", headers=headers).status == 404
        assert app.call("GET", "/health?x=1", headers=headers).status == 404


def test_invalid_bodies_are_bad_requests_and_never_reach_the_turn() -> None:
    bodies = [
        b"not json",
        b"[]",
        b"7",
        b"{}",
        json.dumps({**GOOD, "extra": 1}).encode(),
        json.dumps({**GOOD, "mode": "turbo"}).encode(),
        json.dumps({**GOOD, "session_id": "short"}).encode(),
        json.dumps({**GOOD, "message": "   "}).encode(),
        b'{"session_id": "session-0001", "message": "a", "message": "b", "mode": "gist"}',
        b"\xff\xfe",
        b"[" * 3000,
    ]
    turn = FakeTurn()
    with started(turn) as app:
        for body in bodies:
            reply = app.call("POST", "/generate", body, JSON_HEADERS)
            assert (reply.status, error_type(reply)) == (400, "invalid_request"), body
    assert turn.calls == []


def test_only_json_content_is_accepted() -> None:
    body = json.dumps(GOOD).encode()
    with started() as app:
        for kind in ("text/plain", "application/x-www-form-urlencoded", ""):
            reply = app.call(
                "POST", "/generate", body, {SECRET_HEADER: SECRET, "content-type": kind}
            )
            assert reply.status == 400
        none = app.call("POST", "/generate", body, {SECRET_HEADER: SECRET})
        assert none.status == 400
        charset = {**JSON_HEADERS, "content-type": "application/json; charset=utf-8"}
        assert app.call("POST", "/generate", body, charset).status == 200


def test_a_long_message_is_too_long() -> None:
    with started() as app:
        reply = app.generate({**GOOD, "message": "x" * (LIMITS.max_message_chars + 1)})
    assert (reply.status, error_type(reply)) == (413, "too_long")


def test_an_oversize_declared_body_is_refused_without_reading_it() -> None:
    with started(FakeTurn()) as app:
        head = app.head({"content-type": "application/json", "content-length": "4097"})
        reply = app.raw(head)
    assert (reply.status, error_type(reply)) == (413, "too_long")


@pytest.mark.parametrize(
    "extra",
    [
        {"content-type": "application/json"},
        {"content-type": "application/json", "content-length": "abc"},
        {"content-type": "application/json", "content-length": "-5"},
        {"content-type": "application/json", "transfer-encoding": "chunked"},
        {"content-type": "application/json", "content-length": "5, 6"},
    ],
)
def test_content_length_is_required_and_strict(extra: dict[str, str]) -> None:
    with started() as app:
        reply = app.raw(app.head(extra), b"{}")
    assert (reply.status, error_type(reply)) == (400, "invalid_request")


def test_a_zero_length_body_is_refused() -> None:
    with started() as app:
        reply = app.raw(app.head({"content-type": "application/json", "content-length": "0"}))
    assert (reply.status, error_type(reply)) == (400, "invalid_request")


def test_two_content_length_headers_are_refused() -> None:
    with started() as app:
        head = app.head({"content-type": "application/json", "content-length": "2"})
        reply = app.raw(head.replace(b"\r\n\r\n", b"\r\ncontent-length: 2\r\n\r\n"), b"{}")
    assert reply.status == 400


def test_a_body_that_stops_short_is_refused_after_the_socket_timeout() -> None:
    with started(limits=quick_limits(0.3)) as app:
        head = app.head({"content-type": "application/json", "content-length": "100"})
        began = time.monotonic()
        reply = app.raw(head, b'{"session_id"')
    assert reply.status == 400
    assert time.monotonic() - began < PATIENCE


def trickle(client: socket.socket, began: float) -> None:
    with contextlib.suppress(OSError):
        while time.monotonic() - began < 1.4:
            client.sendall(b"x")
            time.sleep(0.15)


def test_a_slow_trickle_is_cut_off_by_the_total_read_deadline() -> None:
    with started(limits=quick_limits(0.4)) as app:
        head = app.head({"content-type": "application/json", "content-length": "200"})
        began = time.monotonic()
        with socket.create_connection(("127.0.0.1", app.port), timeout=PATIENCE) as client:
            client.sendall(head)
            threading.Thread(target=trickle, args=(client, began), daemon=True).start()
            data = client.recv(65536)
    assert data.startswith(b"HTTP/1.1 400")
    assert time.monotonic() - began < 1.2


def test_an_internal_failure_is_a_500_without_exception_text() -> None:
    turn = FakeTurn(failure=RuntimeError(f"boom {INTERNAL_CANARY}"))
    with started(turn) as app:
        reply = app.generate(GOOD)
    assert (reply.status, error_type(reply)) == (500, "internal")
    assert reply.json() == {"error": {"type": "internal"}}
    assert b"boom" not in reply.body
    assert INTERNAL_CANARY.encode() not in reply.body


def test_a_slow_turn_is_a_504_timeout() -> None:
    hold = threading.Event()
    with started(FakeTurn(hold=hold), limits=limited(total_deadline_s=0.2)) as app:
        reply = app.generate(GOOD)
        hold.set()
    assert (reply.status, error_type(reply)) == (504, "timeout")
    assert "retry-after" not in reply.headers


def test_a_full_queue_is_a_503_busy_with_retry_after() -> None:
    hold = threading.Event()
    turn = FakeTurn(hold=hold)
    with started(turn, limits=limited(max_waiting=1)) as app:
        first = threading.Thread(
            target=app.generate, args=({**GOOD, "session_id": "session-aaaa"},)
        )
        second = threading.Thread(
            target=app.generate, args=({**GOOD, "session_id": "session-bbbb"},)
        )
        first.start()
        assert turn.started.wait(PATIENCE)
        second.start()
        for _ in range(int(PATIENCE * 1000)):
            if app.service.health().waiting == 1:
                break
            threading.Event().wait(0.001)
        reply = app.generate({**GOOD, "session_id": "session-cccc"})
        hold.set()
        first.join(PATIENCE)
        second.join(PATIENCE)
    assert reply.status == 503
    assert reply.json() == {"error": {"type": "busy", "retry_after_s": LIMITS.retry_after_s}}
    assert reply.headers["retry-after"] == str(LIMITS.retry_after_s)
    assert len(turn.calls) == 2


def test_compare_flow_over_http() -> None:
    turn = FakeTurn(["gist answer", "full answer"])
    with started(turn) as app:
        assert app.generate({**GOOD, "mode": "full"}).status == 409
        assert app.generate(GOOD).json()["answer"] == "gist answer"
        compared = app.generate({**GOOD, "mode": "full"})
        mismatch = app.generate({**GOOD, "mode": "full", "message": "something else"})
    assert compared.status == 200
    assert compared.json()["answer"] == "full answer"
    assert (mismatch.status, error_type(mismatch)) == (409, "compare_unavailable")
    assert [call.mode for call in turn.calls] == ["gist", "full"]


def test_the_secret_is_checked_before_the_body_is_parsed() -> None:
    with started() as app:
        reply = app.call("POST", "/generate", b"not json", {"content-type": "application/json"})
    assert reply.status == 401
