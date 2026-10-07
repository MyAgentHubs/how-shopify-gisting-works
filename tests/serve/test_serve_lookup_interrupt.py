import json
import threading
from dataclasses import dataclass
from typing import Any

from runner_support import GOOD_EMAIL, Rig, RigTurn, asking, lookup_call, lookup_parts
from serve_http import limited, started
from serve_support import PATIENCE, Call, FakeTurn, record_read

from gisting.serve.lookups import LookupReads
from gisting.shopify.results import Result
from gisting.shopify.target import DEV_STORE
from gisting.shopify.transport import Request
from gisting.tools.reads import LookupRead

SESSION = "interrupt-session-4417"
SHORT = 0.3
FINISHED = LookupRead(12.5, "Found", False)
CUT_OFF_TYPE = "DeadlineExceeded"


@dataclass
class Exploding:
    error: Exception
    store: str = DEV_STORE

    def execute(self, request: Request) -> Result:
        raise self.error


def body() -> dict[str, str]:
    return {"session_id": SESSION, "message": asking(GOOD_EMAIL)[0].content, "mode": "gist"}


def generate_records(log: str) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in log.splitlines()]
    return [record for record in records if record["event"] == "generate"]


def test_an_interrupted_slot_is_labelled_with_the_error_and_the_time_it_ran() -> None:
    ticks = iter([1.0, 1.25])
    reads = LookupReads(lambda: next(ticks))
    reads.begin().interrupt("X")
    assert reads.snapshot() == (LookupRead(250.0, "X", False),)


def test_a_lookup_that_raises_inside_is_logged_under_the_error_type_in_the_500_line() -> None:
    turn = RigTurn(rig=Rig(lookup=lookup_parts(Exploding(RuntimeError("internal detail")))))
    turn.rig.gist_model.outputs.append(lookup_call(GOOD_EMAIL))
    with started(turn) as app:
        reply = app.generate(body())
        log = app.log.getvalue()
    (record,) = generate_records(log)
    assert (reply.status, record["status"]) == (500, 500)
    (read,) = record["lookups"]
    assert (read["result_type"], read["cache_hit"]) == ("RuntimeError", False)
    assert isinstance(read["shopify_ms"], float)
    assert "internal detail" not in log


def test_a_timed_out_turn_logs_the_finished_read_then_the_cut_off_one() -> None:
    hold = threading.Event()

    def act(call: Call) -> None:
        record_read(call.reads, FINISHED)
        call.reads.begin()
        assert hold.wait(PATIENCE)

    with started(FakeTurn(act=act), limits=limited(total_deadline_s=SHORT)) as app:
        reply = app.generate(body())
        log = app.log.getvalue()
        hold.set()
    (record,) = generate_records(log)
    assert reply.status == 504
    first, second = record["lookups"]
    assert first == {"shopify_ms": 12.5, "result_type": "Found", "cache_hit": False}
    assert (second["result_type"], second["cache_hit"]) == (CUT_OFF_TYPE, False)
    assert isinstance(second["shopify_ms"], float)
