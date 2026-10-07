import json
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from runner_support import GOOD_EMAIL, NUMBER, WRONG_EMAIL, RigTurn, asking, lookup_call
from serve_http import JSON_HEADERS, SECRET, limited, started
from serve_support import INTERNAL_CANARY, PATIENCE, Call, FakeTurn, record_read

from gisting.agent.state import TurnResult
from gisting.prompt.messages import Message
from gisting.serve.lookups import LookupReads
from gisting.serve.scope import TurnScope
from gisting.tools.reads import LookupRead

SESSION = "failed-turn-session-5521"
DIGEST = "ab" * 32
DIGEST_HEADER = "x-gisting-ip-digest"
ORDER = f"#{NUMBER}"
SHORT = 0.3
LOOKUP_KEYS = {"shopify_ms", "result_type", "cache_hit"}
BOOM = f"boom {GOOD_EMAIL} {ORDER} {INTERNAL_CANARY}"
HIDDEN = (ORDER, GOOD_EMAIL, WRONG_EMAIL, SESSION, DIGEST, INTERNAL_CANARY, SECRET, "GLR-")
FIRST = LookupRead(12.5, "Found", False)
SECOND = LookupRead(None, "Found", True)
FIRST_LOGGED = {"shopify_ms": 12.5, "result_type": "Found", "cache_hit": False}
WITH_DIGEST = {**JSON_HEADERS, DIGEST_HEADER: DIGEST}
WRITERS = 8
PER_WRITER = 100


def body_for(email: str = GOOD_EMAIL) -> dict[str, str]:
    return {"session_id": SESSION, "message": asking(email)[0].content, "mode": "gist"}


def records_of(log: str, event: str = "generate") -> list[dict[str, Any]]:
    records = [json.loads(line) for line in log.splitlines()]
    return [record for record in records if record["event"] == event]


def rig_turn(then: Callable[[], None]) -> RigTurn:
    turn = RigTurn(then=then)
    turn.rig.gist_model.outputs.append(lookup_call(GOOD_EMAIL))
    return turn


def stall(hold: threading.Event) -> None:
    hold.wait(PATIENCE)


def raise_boom() -> None:
    raise RuntimeError(BOOM)


def assert_nothing_identifying(text: str) -> None:
    for secret in HIDDEN:
        assert secret not in text


def test_a_timed_out_turn_logs_the_lookups_that_had_finished() -> None:
    hold = threading.Event()
    turn = rig_turn(lambda: stall(hold))
    with started(turn, limits=limited(total_deadline_s=SHORT)) as app:
        reply = app.generate(body_for(), WITH_DIGEST)
        hold.set()
        log = app.log.getvalue()
    (record,) = records_of(log)
    assert (reply.status, record["status"], record["error_type"]) == (504, 504, "timeout")
    (read,) = record["lookups"]
    assert set(read) == LOOKUP_KEYS
    assert (read["result_type"], read["cache_hit"]) == ("Found", False)
    assert isinstance(read["shopify_ms"], float)
    assert_nothing_identifying(log)


def test_an_internal_error_turn_logs_the_lookups_that_had_finished() -> None:
    with started(rig_turn(raise_boom)) as app:
        reply = app.generate(body_for(), WITH_DIGEST)
        log = app.log.getvalue()
    (record,) = records_of(log)
    assert (reply.status, record["status"]) == (500, 500)
    assert record["error_type"] == "internal:RuntimeError"
    assert [read["result_type"] for read in record["lookups"]] == ["Found"]
    assert_nothing_identifying(log)


def test_a_failed_turn_without_a_lookup_logs_no_lookups_key() -> None:
    with started(FakeTurn(failure=RuntimeError(BOOM))) as app:
        app.generate(body_for())
        log = app.log.getvalue()
    (record,) = records_of(log)
    assert record["status"] == 500
    assert "lookups" not in record


def test_failed_responses_never_carry_the_lookup_reads() -> None:
    hold = threading.Event()
    slow = rig_turn(lambda: stall(hold))
    broken = rig_turn(raise_boom)
    for turn, limits in ((slow, limited(total_deadline_s=SHORT)), (broken, limited())):
        with started(turn, limits=limits) as app:
            reply = app.generate(body_for())
            hold.set()
        text = reply.body.decode() + json.dumps(reply.headers)
        for needle in ("shopify_ms", "lookups", "cache_hit", "result_type", "Found"):
            assert needle not in text


def test_a_job_that_keeps_reading_after_the_timeout_changes_nothing_already_logged() -> None:
    hold, finished = threading.Event(), threading.Event()

    def act(call: Call) -> None:
        record_read(call.reads, FIRST)
        assert hold.wait(PATIENCE)
        record_read(call.reads, SECOND)
        finished.set()

    with started(FakeTurn(act=act), limits=limited(total_deadline_s=SHORT)) as app:
        reply = app.generate(body_for())
        before = app.log.getvalue()
        hold.set()
        assert finished.wait(PATIENCE)
        for _ in range(int(PATIENCE * 1000)):
            if app.service.health().status == "ready":
                break
            threading.Event().wait(0.001)
        after = app.log.getvalue()
        health = app.service.health().status
    assert reply.status == 504
    assert after == before
    (record,) = records_of(after)
    assert record["lookups"] == [FIRST_LOGGED]
    assert records_of(after, "error") == []
    assert health == "ready"


def test_a_busy_request_logs_no_lookups_even_while_another_request_holds_reads() -> None:
    hold = threading.Event()
    turn = FakeTurn(hold=hold, act=lambda call: record_read(call.reads, FIRST))
    with started(turn, limits=limited(max_waiting=0)) as app:
        running = threading.Thread(target=app.generate, args=(body_for(),))
        running.start()
        assert turn.started.wait(PATIENCE)
        busy = app.generate({**body_for(), "session_id": "busy-session-0002"})
        hold.set()
        running.join(PATIENCE)
        log = app.log.getvalue()
    assert busy.status == 503
    by_status = {record["status"]: record for record in records_of(log)}
    assert set(by_status) == {200, 503}
    assert "lookups" not in by_status[503]


def test_not_ready_and_compare_unavailable_log_no_lookups() -> None:
    with started(FakeTurn(), ready=False) as app:
        assert app.generate(body_for()).status == 503
        assert "lookups" not in records_of(app.log.getvalue())[0]
    with started(FakeTurn()) as app:
        assert app.generate({**body_for(), "mode": "full"}).status == 409
        assert "lookups" not in records_of(app.log.getvalue())[0]


def test_each_request_starts_with_an_empty_sink() -> None:
    sinks: list[Any] = []

    def act(call: Call) -> None:
        sinks.append(call.reads)
        if len(sinks) == 1:
            record_read(call.reads, FIRST)

    with started(FakeTurn(act=act)) as app:
        app.generate(body_for())
        app.generate({**body_for(), "message": "and then"})
    assert sinks[0] is not sinks[1]
    assert sinks[1].snapshot() == ()


def test_a_snapshot_is_a_value_that_later_appends_do_not_change() -> None:
    reads = LookupReads()
    record_read(reads, FIRST)
    taken = reads.snapshot()
    record_read(reads, SECOND)
    assert taken == (FIRST,)
    assert reads.snapshot() == (FIRST, SECOND)


@dataclass
class Watcher:
    reads: LookupReads
    stop: threading.Event = field(default_factory=threading.Event)
    seen: list[tuple[LookupRead, ...]] = field(default_factory=lambda: [])

    def run(self) -> None:
        while not self.stop.is_set():
            self.keep(self.reads.snapshot())
        self.keep(self.reads.snapshot())

    def keep(self, snapshot: tuple[LookupRead, ...]) -> None:
        if not self.seen or len(self.seen[-1]) != len(snapshot):
            self.seen.append(snapshot)


def write_many(reads: LookupReads, number: int) -> None:
    for _ in range(PER_WRITER):
        record_read(reads, LookupRead(float(number), "Found", None))
        time.sleep(0)


def test_concurrent_appends_and_snapshots_never_lose_or_tear_a_read() -> None:
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        check_concurrent_appends()
    finally:
        sys.setswitchinterval(interval)


def check_concurrent_appends() -> None:
    reads = LookupReads()
    watcher = Watcher(reads)
    watching = threading.Thread(target=watcher.run)
    watching.start()
    writers = [
        threading.Thread(target=write_many, args=(reads, number)) for number in range(WRITERS)
    ]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(PATIENCE)
    watcher.stop.set()
    watching.join(PATIENCE)
    final = reads.snapshot()
    assert len(final) == WRITERS * PER_WRITER
    sizes = [len(seen) for seen in watcher.seen]
    assert sizes == sorted(sizes)
    for seen in watcher.seen:
        for index, read in enumerate(seen):
            assert read in (final[index], LookupRead(read.shopify_ms, "DeadlineExceeded", False))
    assert all(read.result_type == "Found" for read in final)


def test_the_sink_handed_to_the_turn_is_the_one_the_log_reports() -> None:
    handed: list[object] = []

    def turn(mode: str, session_id: str, history: list[Message], scope: TurnScope) -> TurnResult:
        handed.append(scope.reads)
        record_read(scope.reads, FIRST)
        raise RuntimeError(BOOM)

    with started(FakeTurn()) as app:
        app.service.turn = turn
        reply = app.generate(body_for())
        log = app.log.getvalue()
    assert reply.status == 500
    assert isinstance(handed[0], LookupReads)
    (record,) = records_of(log)
    assert record["lookups"] == [FIRST_LOGGED]
