import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from runner_support import GOOD_EMAIL, Rig, RigTurn, asking, lookup_call, lookup_parts
from serve_http import limited, started
from serve_support import PATIENCE

from gisting.shopify.results import Result, Uncertain
from gisting.shopify.target import DEV_STORE
from gisting.shopify.transport import Request

SESSION = "cut-off-session-7731"
BUDGET_S = 0.3
SLACK_S = 0.5


@dataclass
class Stalling:
    hold: threading.Event
    store: str = DEV_STORE
    entered: threading.Event = field(default_factory=threading.Event)

    def execute(self, request: Request) -> Result:
        self.entered.set()
        self.hold.wait(PATIENCE)
        return Uncertain("late")


def generate_records(log: str) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in log.splitlines()]
    return [record for record in records if record["event"] == "generate"]


def body() -> dict[str, str]:
    return {"session_id": SESSION, "message": asking(GOOD_EMAIL)[0].content, "mode": "gist"}


def test_a_shopify_read_that_outlives_the_deadline_is_in_the_504_log_line() -> None:
    hold = threading.Event()
    transport = Stalling(hold)
    turn = RigTurn(rig=Rig(lookup=lookup_parts(transport)))
    turn.rig.gist_model.outputs.append(lookup_call(GOOD_EMAIL))
    with started(turn, limits=limited(total_deadline_s=BUDGET_S)) as app:
        begun = time.monotonic()
        reply = app.generate(body())
        waited = time.monotonic() - begun
        assert transport.entered.is_set()
        before = app.log.getvalue()
        hold.set()
        for _ in range(int(PATIENCE * 1000)):
            if app.service.health().status == "ready":
                break
            threading.Event().wait(0.001)
        after = app.log.getvalue()
    (record,) = generate_records(before)
    (read,) = record["lookups"]
    assert (reply.status, record["status"], record["error_type"]) == (504, 504, "timeout")
    assert (read["result_type"], read["cache_hit"]) == ("DeadlineExceeded", False)
    assert BUDGET_S * 1000 * 0.5 <= read["shopify_ms"] <= (BUDGET_S + SLACK_S) * 1000
    assert waited < BUDGET_S + SLACK_S
    assert after == before


def test_the_cut_off_read_carries_nothing_identifying() -> None:
    hold = threading.Event()
    turn = RigTurn(rig=Rig(lookup=lookup_parts(Stalling(hold))))
    turn.rig.gist_model.outputs.append(lookup_call(GOOD_EMAIL))
    with started(turn, limits=limited(total_deadline_s=BUDGET_S)) as app:
        reply = app.generate(body())
        hold.set()
        log = app.log.getvalue()
    (record,) = generate_records(log)
    assert set(record["lookups"][0]) == {"shopify_ms", "result_type", "cache_hit"}
    text = log + reply.body.decode() + json.dumps(reply.headers)
    for secret in (GOOD_EMAIL, SESSION, "#1042", "GLR-"):
        assert secret not in text
    assert "lookups" not in reply.body.decode()
