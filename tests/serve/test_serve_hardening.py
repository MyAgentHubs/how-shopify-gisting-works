import json
import re
import socket
import threading
import time
from collections.abc import Callable
from typing import cast

import pytest
from serve_http import GOOD_SESSION, JSON_HEADERS, SECRET, Reply, limited, started
from serve_support import PATIENCE, FakeTurn

from gisting.serve.app import SECRET_HEADER, AppContext, make_server
from gisting.serve.config import ConfigError
from gisting.serve.store import StoreLimits

GOOD = {"session_id": GOOD_SESSION, "message": "where is my order", "mode": "gist"}
HEALTH_HEADERS = {SECRET_HEADER: SECRET}
CANARY = "CANARY-BOOM-9921"


def padded(value: str) -> str:
    return value + " "


def error_type(reply: Reply) -> str:
    error = cast(dict[str, object], reply.json()["error"])
    return str(error["type"])


def test_a_lone_surrogate_is_refused_and_the_session_history_survives() -> None:
    turn = FakeTurn(["r1", "r2", "r3"])
    with started(turn) as app:
        for message in ("first", "second"):
            assert app.generate({**GOOD, "message": message}).status == 200
        body = json.dumps({**GOOD, "message": "x"}).replace('"x"', '"\\ud83d"').encode()
        reply = app.call("POST", "/generate", body, JSON_HEADERS)
        assert (reply.status, error_type(reply)) == (400, "invalid_request")
        assert app.generate({**GOOD, "message": "third"}).status == 200
    assert len(turn.calls[-1].history) == 5


@pytest.mark.parametrize(
    ("length", "status", "kind"),
    [
        ("9" * 5000, 413, "too_long"),
        ("1" + "0" * 4400, 413, "too_long"),
        ("0" * 5000 + "2", 400, "invalid_request"),
        ("２", 400, "invalid_request"),
        ("+2", 400, "invalid_request"),
        ("2.0", 400, "invalid_request"),
        ("0x2", 400, "invalid_request"),
        ("0" * 5000, 400, "invalid_request"),
    ],
)
def test_odd_content_length_values_never_crash_the_server(
    length: str, status: int, kind: str
) -> None:
    with started() as app:
        head = app.head({"content-type": "application/json", "content-length": length})
        reply = app.raw(head, b"{}")
        assert (reply.status, error_type(reply)) == (status, kind)
        assert app.call("GET", "/health", headers=HEALTH_HEADERS).status == 200


def test_content_length_with_transfer_encoding_is_refused() -> None:
    with started() as app:
        head = app.head({
            "content-type": "application/json",
            "content-length": "2",
            "transfer-encoding": "chunked",
        })
        reply = app.raw(head, b"{}")
    assert (reply.status, error_type(reply)) == (400, "invalid_request")


def test_health_is_unavailable_while_a_turn_overruns_its_deadline() -> None:
    hold = threading.Event()
    turn = FakeTurn(hold=hold)
    with started(turn, limits=limited(total_deadline_s=0.2)) as app:
        assert app.generate(GOOD).status == 504
        stuck = app.call("GET", "/health", headers=HEALTH_HEADERS)
        assert stuck.status == 503
        assert stuck.json()["status"] == "loading"
        again = app.generate(GOOD)
        assert (again.status, error_type(again)) == (503, "not_ready")
        hold.set()
        for _ in range(int(PATIENCE * 1000)):
            if app.call("GET", "/health", headers=HEALTH_HEADERS).status == 200:
                break
            threading.Event().wait(0.001)
        assert app.call("GET", "/health", headers=HEALTH_HEADERS).status == 200


def test_going_over_the_session_limit_is_logged_as_a_named_event_without_content() -> None:
    limits = StoreLimits(900.0, 500, 1, 16384)
    with started(FakeTurn(["r1", "r2"]), store_limits=limits) as app:
        app.generate({**GOOD, "message": "first CANARY-RESET-TEXT"})
        app.generate({**GOOD, "message": "second CANARY-RESET-TEXT"})
        records = [json.loads(line) for line in app.log.getvalue().splitlines()]
    events = [record["event"] for record in records]
    assert events == ["generate", "session_reset_over_limit", "generate"]
    assert "CANARY-RESET-TEXT" not in json.dumps(records)
    assert set(records[1]) == {"ts", "event", "session", "mode"}


def trickle(client: socket.socket, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            client.sendall(b"a")
        except OSError:
            return
        stop.wait(0.05)


def first_bytes(client: socket.socket) -> bytes:
    try:
        return client.recv(65536)
    except ConnectionResetError:
        return b""


def test_the_header_phase_has_a_total_deadline_against_slow_trickles() -> None:
    stop = threading.Event()
    with started(limits=limited(socket_timeout_s=0.3)) as app:
        began = time.monotonic()
        with socket.create_connection(("127.0.0.1", app.port), timeout=PATIENCE) as client:
            client.sendall(b"POST /generate HTTP/1.1\r\nHost: x")
            thread = threading.Thread(target=trickle, args=(client, stop), daemon=True)
            thread.start()
            data = first_bytes(client)
            stop.set()
            thread.join(PATIENCE)
        assert data == b""
        assert time.monotonic() - began < 1.5
        assert app.call("GET", "/health", headers=HEALTH_HEADERS).status == 200


def test_two_secret_headers_or_two_host_headers_are_unauthorized() -> None:
    with started() as app:
        single = app.head({"content-type": "application/json", "content-length": "2"})
        assert app.raw(single, b"{}").status == 400
        twice = single.replace(b"\r\n\r\n", f"\r\n{SECRET_HEADER}: {SECRET}\r\n\r\n".encode())
        assert app.raw(twice, b"{}").status == 401
        wrong_second = single.replace(b"\r\n\r\n", f"\r\n{SECRET_HEADER}: wrong\r\n\r\n".encode())
        assert app.raw(wrong_second, b"{}").status == 401
        host = f"host: 127.0.0.1:{app.port}".encode()
        assert app.raw(single.replace(host, host + b"\r\n" + host), b"{}").status == 401


@pytest.mark.parametrize("variant", [str.upper, str.swapcase, padded])
def test_the_secret_comparison_is_exact_and_case_sensitive(variant: Callable[[str], str]) -> None:
    changed = variant(SECRET)
    assert changed != SECRET
    with started() as app:
        reply = app.call("GET", "/health", headers={SECRET_HEADER: changed})
    assert reply.status == 401


def test_the_secret_never_appears_in_the_context_repr() -> None:
    with started() as app:
        text = repr(app.server.context)
    assert SECRET not in text
    assert SECRET.encode().decode("latin-1") not in text


@pytest.mark.parametrize("secret", [b"", b"short-secret", b" " + b"x" * 40, b"x" * 40 + b" "])
def test_the_server_refuses_to_start_with_a_weak_secret(secret: bytes) -> None:
    with started() as app:
        context = app.server.context
    weak = AppContext(context.service, context.logs, secret, context.limits)
    with pytest.raises(ConfigError):
        make_server(0, weak)


def test_an_unexpected_failure_is_logged_by_type_and_site_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> object:
        raise RuntimeError(CANARY)

    with started() as app:
        monkeypatch.setattr(app.service, "health", boom)
        reply = app.call("GET", "/health", headers=HEALTH_HEADERS)
        assert (reply.status, error_type(reply)) == (500, "internal")
        for _ in range(int(PATIENCE * 1000)):
            if '"event":"error"' in app.log.getvalue().replace(" ", ""):
                break
            threading.Event().wait(0.001)
        records = [json.loads(line) for line in app.log.getvalue().splitlines()]
    errors = [record for record in records if record["event"] == "error"]
    assert len(errors) == 1
    assert errors[0]["error_type"] == "RuntimeError"
    assert re.fullmatch(r"test_serve_hardening\.py:boom:\d+", errors[0]["where"])
    text = app.log.getvalue()
    assert CANARY not in text
    assert "RuntimeError(" not in text
    assert CANARY.encode() not in reply.body
