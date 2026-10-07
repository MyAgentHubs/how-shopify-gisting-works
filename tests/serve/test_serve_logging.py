import json
import threading

import pytest
from serve_http import JSON_HEADERS, SECRET, limited, started
from serve_support import INTERNAL_CANARY, FakeTurn

from gisting.agent.policy import FallbackReason
from gisting.serve.app import SECRET_HEADER, AppContext, make_server
from gisting.serve.config import ConfigError
from gisting.serve.logs import LogRecord, RequestLog

MESSAGE_CANARY = "CANARY-MSG-8841"
ORDER = "#1042"
EMAIL = "canary.buyer@example.test"
SESSION = "canary-session-5521"
ANSWER_CANARY = "ANSWER-CANARY-7710"
EXCEPTION_CANARY = "EXC-CANARY-3392"
HEADER_CANARY = "CANARY-WRONG-SECRET"
PATH_CANARY = "CANARY-PATH-6604"
CUSTOMER_TEXT = f"Where is order {ORDER}? my email is {EMAIL} {MESSAGE_CANARY}"
CANARIES = (
    MESSAGE_CANARY,
    ORDER,
    EMAIL,
    SESSION,
    ANSWER_CANARY,
    EXCEPTION_CANARY,
    HEADER_CANARY,
    PATH_CANARY,
    INTERNAL_CANARY,
    SECRET,
)
ALLOWED_KEYS = set(LogRecord.__dataclass_fields__) | {"ts"}


def gist(message: str = CUSTOMER_TEXT) -> dict[str, str]:
    return {"session_id": SESSION, "message": message, "mode": "gist"}


def scenario_log() -> str:
    logs: list[str] = []
    answer = f"Order {ORDER} for {EMAIL} ships soon {ANSWER_CANARY}"
    with started(FakeTurn([answer, answer], fallback=FallbackReason.EMPTY_ANSWER)) as app:
        app.generate(gist())
        app.generate({**gist(), "mode": "full"})
        app.generate(gist(), {**JSON_HEADERS, SECRET_HEADER: HEADER_CANARY})
        app.call("POST", "/generate", f'{{"message": "{CUSTOMER_TEXT}"'.encode(), JSON_HEADERS)
        app.generate(gist("x" * 400 + CUSTOMER_TEXT))
        app.call("GET", f"/orders/{PATH_CANARY}", headers={SECRET_HEADER: SECRET})
        app.call("GET", "/health", headers={SECRET_HEADER: SECRET})
        logs.append(app.log.getvalue())
    failing = FakeTurn(
        failure=RuntimeError(f"{EXCEPTION_CANARY} {CUSTOMER_TEXT} {INTERNAL_CANARY}")
    )
    with started(failing) as app:
        app.generate(gist())
        logs.append(app.log.getvalue())
    hold = threading.Event()
    with started(FakeTurn(hold=hold), limits=limited(total_deadline_s=0.2)) as app:
        app.generate(gist())
        hold.set()
        logs.append(app.log.getvalue())
    with started(ready=False) as app:
        app.generate(gist())
        logs.append(app.log.getvalue())
    return "".join(logs)


def test_no_canary_ever_reaches_the_log_or_stderr(capfd: pytest.CaptureFixture[str]) -> None:
    text = scenario_log()
    captured = capfd.readouterr()
    assert text.strip()
    for canary in CANARIES:
        assert text.count(canary) == 0, canary
        assert captured.err.count(canary) == 0, canary
        assert captured.out.count(canary) == 0, canary
    assert captured.err == ""


def test_every_line_is_json_with_only_the_allowed_keys() -> None:
    text = scenario_log()
    records = [json.loads(line) for line in text.splitlines()]
    assert records
    for record in records:
        assert set(record) <= ALLOWED_KEYS
        assert {"ts", "event"} <= set(record)


def test_the_log_records_what_happened_without_content() -> None:
    records = [json.loads(line) for line in scenario_log().splitlines()]
    generated = [record for record in records if record["event"] == "generate"]
    statuses = {record["status"] for record in records}
    assert {200, 400, 401, 404, 413, 500, 503, 504} <= statuses
    served = generated[0]
    assert served["status"] == 200
    assert served["mode"] == "gist"
    assert served["reply_source"] == "template"
    assert served["fallback_reason"] == "empty_answer"
    assert served["tokens"] == 321
    assert served["queue_ms"] >= 0
    assert served["run_ms"] >= 0
    assert len(served["session"]) == 8
    assert generated[1]["session"] == served["session"]
    failure = next(record for record in generated if record["status"] == 500)
    assert failure["error_type"] == "internal:RuntimeError"


def test_the_server_refuses_to_start_without_a_secret() -> None:
    with started() as app:
        context = app.server.context
    broken = AppContext(context.service, RequestLog(app.log), b"", context.limits)
    with pytest.raises(ConfigError):
        make_server(0, broken)
