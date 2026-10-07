import json
from pathlib import Path

import pytest
from serve_http import GOOD_SESSION, JSON_HEADERS, Running, started
from serve_support import Call, FakeTurn

from gisting.serve.app import SECRET_HEADER
from gisting.serve.config import ConfigError, load_limits
from gisting.serve.contract import RequestRejected
from gisting.serve.failures import IP_KIND
from gisting.serve.ip_digest import read_ip_digest

ROOT = Path(__file__).resolve().parents[2]
DIGEST_HEADER = "x-gisting-ip-digest"
DIGEST_A = "a" * 64
DIGEST_B = "0123456789abcdef" * 4
UNKNOWN_KEY = (IP_KIND, "unknown")
BAD_VALUES = [
    "a" * 63,
    "a" * 65,
    "A" * 64,
    "g" * 64,
    "unknown",
    "a" * 32 + "-" + "a" * 31,
    "é" + "a" * 63,
    "a" * 64 + "\n",
]
BODY = json.dumps({"session_id": GOOD_SESSION, "message": "where is my order", "mode": "gist"})


def with_digest(value: str) -> dict[str, str]:
    return {**JSON_HEADERS, DIGEST_HEADER: value}


def session_body(index: int) -> dict[str, str]:
    return {"session_id": f"session-{index:04d}", "message": "where is my order", "mode": "gist"}


def fail_once(call: Call) -> None:
    call.failures.record_failure(call.session_id)


def raw_post(app: Running, digest_lines: list[str]) -> int:
    payload = BODY.encode()
    lines = [
        "POST /generate HTTP/1.1",
        f"host: 127.0.0.1:{app.port}",
        f"{SECRET_HEADER}: {JSON_HEADERS[SECRET_HEADER]}",
        "content-type: application/json",
        f"content-length: {len(payload)}",
        *digest_lines,
    ]
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
    return app.raw(head + payload).status


def test_a_valid_digest_failures_accumulate_in_its_own_ip_bucket_across_sessions() -> None:
    turn = FakeTurn(act=fail_once)
    with started(turn) as app:
        for index in range(3):
            assert app.generate(session_body(index), with_digest(DIGEST_A)).status == 200
        assert app.generate(session_body(9), with_digest(DIGEST_B)).status == 200
        counts = app.service.failures.count
        assert counts((IP_KIND, DIGEST_A)) == 3
        assert counts((IP_KIND, DIGEST_B)) == 1
        assert counts(UNKNOWN_KEY) == 0


def test_a_digest_that_reached_the_ip_limit_locks_new_sessions_but_not_another_digest() -> None:
    locked: dict[str, bool] = {}

    def probe(call: Call) -> None:
        locked[call.session_id] = call.failures.is_locked(call.session_id)
        fail_once(call)

    turn = FakeTurn(act=probe)
    with started(turn) as app:
        limit = app.server.context.limits.ip_failure_limit
        for index in range(limit):
            app.generate(session_body(index), with_digest(DIGEST_A))
        app.generate(session_body(500), with_digest(DIGEST_A))
        app.generate(session_body(501), with_digest(DIGEST_B))
    assert locked["session-0500"] is True
    assert locked["session-0501"] is False
    assert not any(locked[f"session-{index:04d}"] for index in range(limit))


@pytest.mark.parametrize("headers", [JSON_HEADERS, with_digest("")])
def test_a_missing_or_empty_digest_reaches_the_service_as_none(headers: dict[str, str]) -> None:
    turn = FakeTurn(act=fail_once)
    with started(turn) as app:
        assert app.generate(session_body(1), headers).status == 200
        assert app.service.failures.count(UNKNOWN_KEY) == 1
        assert app.service.failures.stats().ip_digest_missing == 1


def test_a_valid_digest_is_passed_to_handle() -> None:
    seen: list[str | None] = []
    with started() as app:
        original = app.service.handle

        def spy(request: object, ip_digest: str | None = None) -> object:
            seen.append(ip_digest)
            return original(request, ip_digest)  # type: ignore[arg-type]

        app.service.handle = spy  # type: ignore[method-assign]
        app.generate(session_body(1), with_digest(DIGEST_A))
        app.generate(session_body(2))
    assert seen == [DIGEST_A, None]


@pytest.mark.parametrize("value", BAD_VALUES)
def test_an_invalid_digest_is_rejected_before_the_turn_without_logging_its_value(
    value: str,
) -> None:
    turn = FakeTurn()
    with started(turn) as app:
        status = raw_post(app, [f"{DIGEST_HEADER}: {value}"])
        log = app.log.getvalue()
    assert status == 400
    assert turn.calls == []
    assert value not in log
    assert value[:8] not in log
    assert json.loads(log.strip().splitlines()[-1])["error_type"] == "invalid_request"


@pytest.mark.parametrize("second", [DIGEST_A, DIGEST_B, ""])
def test_a_repeated_digest_header_is_rejected(second: str) -> None:
    turn = FakeTurn()
    with started(turn) as app:
        status = raw_post(app, [f"{DIGEST_HEADER}: {DIGEST_A}", f"{DIGEST_HEADER}: {second}"])
        log = app.log.getvalue()
    assert status == 400
    assert turn.calls == []
    assert DIGEST_A not in log
    assert json.loads(log.strip().splitlines()[-1])["event"] == "rejected"


@pytest.mark.parametrize("value", BAD_VALUES)
def test_read_ip_digest_requires_the_pattern_to_match_the_whole_value(value: str) -> None:
    pattern = load_limits(ROOT / "data/serve/limits.json").ip_digest_pattern
    with pytest.raises(RequestRejected):
        read_ip_digest([value], pattern)


def test_an_invalid_digest_error_body_is_the_uniform_invalid_request() -> None:
    with started() as app:
        reply = app.generate(session_body(1), with_digest("unknown"))
    assert reply.status == 400
    assert reply.json() == {"error": {"type": "invalid_request"}}


def test_health_needs_no_digest() -> None:
    with started() as app:
        reply = app.call("GET", "/health", headers={SECRET_HEADER: JSON_HEADERS[SECRET_HEADER]})
    assert reply.status == 200


def test_limits_loader_rejects_a_missing_or_malformed_digest_pattern(tmp_path: Path) -> None:
    good = json.loads((ROOT / "data/serve/limits.json").read_text(encoding="utf-8"))
    cases = [
        {key: value for key, value in good.items() if key != "ipDigestPattern"},
        {**good, "ipDigestPattern": "("},
        {**good, "ipDigestPattern": ""},
        {**good, "ipDigestPattern": 5},
    ]
    for index, document in enumerate(cases):
        path = tmp_path / f"limits{index}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ConfigError):
            load_limits(path)
