import threading

from serve_support import (
    INTERNAL_CANARY,
    PATIENCE,
    PUBLIC_TRACE,
    TOTAL_TOKENS,
    FakeTurn,
    make_service,
)

from gisting.agent.consent import agreed_offer
from gisting.agent.context import without_earlier_orders
from gisting.agent.policy import FallbackReason, load_agent_policy
from gisting.agent.trace import Traces
from gisting.prompt.messages import AssistantMessage, UserMessage
from gisting.serve.config import LIMITS
from gisting.serve.contract import GenerateRequest
from gisting.serve.service import Refused, Served
from gisting.serve.store import StoreLimits
from gisting.tools.policy import load_policy

SESSION = "session-0001"


def gist(message: str, session: str = SESSION) -> GenerateRequest:
    return GenerateRequest(session, message, "gist")


def full(message: str, session: str = SESSION) -> GenerateRequest:
    return GenerateRequest(session, message, "full")


def test_a_good_turn_serves_the_answer_and_only_the_public_trace() -> None:
    turn = FakeTurn(["hello there"])
    handled = make_service(turn).handle(gist("hi"))
    served = handled.result
    assert isinstance(served, Served)
    assert served.answer == "hello there"
    assert served.trace == PUBLIC_TRACE
    assert served.tokens == TOTAL_TOKENS
    assert served.reply_source == "template"
    assert served.fallback_reason is None
    assert INTERNAL_CANARY not in repr(handled)
    assert handled.timing.queue_ms is not None
    assert handled.timing.run_ms is not None


def test_the_history_grows_with_committed_turns() -> None:
    turn = FakeTurn(["r1", "r2"])
    service = make_service(turn)
    service.handle(gist("first"))
    service.handle(gist("second"))
    assert [call.history for call in turn.calls] == [
        (UserMessage("first"),),
        (UserMessage("first"), AssistantMessage("r1"), UserMessage("second")),
    ]
    assert all(call.mode == "gist" and call.session_id == SESSION for call in turn.calls)


def test_sessions_do_not_share_history() -> None:
    turn = FakeTurn()
    service = make_service(turn)
    service.handle(gist("mine", "session-aaaa"))
    service.handle(gist("yours", "session-bbbb"))
    assert turn.calls[1].history == (UserMessage("yours"),)


def test_a_fallback_reply_is_served_with_its_reason_and_committed() -> None:
    turn = FakeTurn(["sorry"], fallback=FallbackReason.EMPTY_ANSWER)
    service = make_service(turn)
    served = service.handle(gist("hi")).result
    assert isinstance(served, Served)
    assert served.fallback_reason == "empty_answer"
    service.handle(gist("again"))
    assert turn.calls[1].history[:2] == (UserMessage("hi"), AssistantMessage("sorry"))


def test_a_failing_turn_is_internal_and_leaves_no_trace_in_the_store() -> None:
    turn = FakeTurn(failure=ValueError(f"order text {INTERNAL_CANARY}"))
    service = make_service(turn)
    handled = service.handle(gist("hi"))
    assert handled.result == Refused("internal", detail="ValueError")
    assert INTERNAL_CANARY not in repr(handled)
    working = FakeTurn()
    service.turn = working
    service.handle(gist("next"))
    assert working.calls[0].history == (UserMessage("next"),)


def test_a_timed_out_turn_is_not_committed() -> None:
    hold = threading.Event()
    turn = FakeTurn(hold=hold)
    service = make_service(turn, total=0.2)
    handled = service.handle(gist("slow one"))
    assert handled.result == Refused("timeout")
    hold.set()
    follow = FakeTurn()
    service.turn = follow
    for _ in range(int(PATIENCE * 1000)):
        if service.health().running == 0:
            break
        threading.Event().wait(0.001)
    service.handle(gist("next"))
    assert follow.calls[0].history == (UserMessage("next"),)


def test_busy_is_refused_with_a_retry_hint_and_not_committed() -> None:
    hold = threading.Event()
    turn = FakeTurn(hold=hold)
    service = make_service(turn, waiting=1)
    runner = threading.Thread(target=service.handle, args=(gist("one", "session-aaaa"),))
    runner.start()
    assert turn.started.wait(PATIENCE)
    waiter = threading.Thread(target=service.handle, args=(gist("two", "session-bbbb"),))
    waiter.start()
    for _ in range(int(PATIENCE * 1000)):
        if service.health().waiting == 1:
            break
        threading.Event().wait(0.001)
    handled = service.handle(gist("three", "session-cccc"))
    assert handled.result == Refused("busy", LIMITS.retry_after_s)
    hold.set()
    runner.join(PATIENCE)
    waiter.join(PATIENCE)
    assert len(turn.calls) == 2


def test_not_ready_refuses_without_running_anything() -> None:
    turn = FakeTurn()
    handled = make_service(turn, ready=False).handle(gist("hi"))
    assert handled.result == Refused("not_ready", LIMITS.retry_after_s)
    assert turn.calls == []


def test_compare_needs_the_same_last_message() -> None:
    turn = FakeTurn()
    service = make_service(turn)
    assert service.handle(full("hi")).result == Refused("compare_unavailable")
    service.handle(gist("hi"))
    assert service.handle(full("other")).result == Refused("compare_unavailable")
    assert len(turn.calls) == 1


def test_compare_reruns_on_the_earlier_history_in_full_mode_without_committing() -> None:
    turn = FakeTurn(["g1", "g2", "f2", "g3"])
    service = make_service(turn)
    service.handle(gist("first"))
    service.handle(gist("second"))
    compared = service.handle(full("second")).result
    assert isinstance(compared, Served)
    assert compared.answer == "f2"
    assert turn.calls[2].mode == "full"
    assert turn.calls[2].history == (
        UserMessage("first"),
        AssistantMessage("g1"),
        UserMessage("second"),
    )
    service.handle(gist("third"))
    assert turn.calls[3].history == (
        UserMessage("first"),
        AssistantMessage("g1"),
        UserMessage("second"),
        AssistantMessage("g2"),
        UserMessage("third"),
    )
    assert service.handle(full("second")).result == Refused("compare_unavailable")


def test_a_public_trace_missing_a_part_is_an_internal_failure() -> None:
    turn = FakeTurn()
    turn.result_traces = Traces({"tools": []}, {"reply_source": "model"})
    handled = make_service(turn).handle(gist("hi"))
    assert handled.result == Refused("internal", detail="TraceRejected")


def test_extra_parts_of_the_public_document_are_dropped() -> None:
    turn = FakeTurn()
    turn.result_traces = Traces({**PUBLIC_TRACE, "internal": INTERNAL_CANARY}, {})
    served = make_service(turn).handle(gist("hi")).result
    assert isinstance(served, Served)
    assert served.trace == PUBLIC_TRACE
    assert served.reply_source is None


def test_an_unknown_reply_source_is_not_passed_on() -> None:
    turn = FakeTurn()
    turn.result_traces = Traces(dict(PUBLIC_TRACE), {"reply_source": INTERNAL_CANARY})
    served = make_service(turn).handle(gist("hi")).result
    assert isinstance(served, Served)
    assert served.reply_source is None


def test_health_reports_readiness_and_load() -> None:
    service = make_service(FakeTurn(), ready=False)
    assert service.health().status == "loading"
    service.ready.set()
    report = service.health()
    assert (report.status, report.running, report.waiting) == ("ready", 0, 0)


ASK_A = "Where is order #1042? My email is a@example.com"
REPLY_A = "Your order is on its way. It is with Test Parcel, tracking number TP-1042."
FOLLOW = "Is it still on its way?"
SWITCH = "And order #1043? My email is b@example.com"


def tight(turns: int) -> StoreLimits:
    return StoreLimits(900.0, 500, turns, 16384)


def test_going_over_the_limit_leaves_no_old_order_fact_in_the_next_model_input() -> None:
    turn = FakeTurn([REPLY_A, REPLY_A, "ok", "fine"])
    service = make_service(turn, store_limits=tight(2))
    service.handle(gist(ASK_A))
    service.handle(gist(FOLLOW))
    switched = service.handle(gist(SWITCH))
    assert switched.timing.session_reset
    before = without_earlier_orders(load_agent_policy(), load_policy(), list(turn.calls[2].history))
    assert before.removed > 0
    assert service.handle(full(SWITCH)).result == Refused("compare_unavailable")
    service.handle(gist("thanks"))
    assert turn.calls[3].history == (UserMessage("thanks"),)
    seen = " ".join(message.content for message in turn.calls[3].history)
    assert "TP-1042" not in seen
    assert "a@example.com" not in seen


def test_a_reset_forgets_the_offer_so_a_yes_after_it_cannot_trigger_a_handoff() -> None:
    guard = load_agent_policy().consent_guards["handoff_to_human"]
    turn = FakeTurn(["Let me check.", f"Sorry. {guard.offer_text}", "noted"])
    service = make_service(turn, store_limits=tight(1))
    service.handle(gist("where is my order"))
    offered = service.handle(gist("it is late"))
    assert offered.timing.session_reset
    service.handle(gist("yes please"))
    history = list(turn.calls[2].history)
    assert not agreed_offer(guard, history)
    assert history == [UserMessage("yes please")]


def test_without_a_reset_a_yes_after_the_offer_is_seen_by_the_guard() -> None:
    guard = load_agent_policy().consent_guards["handoff_to_human"]
    turn = FakeTurn([f"Sorry. {guard.offer_text}", "noted"])
    service = make_service(turn, store_limits=tight(5))
    service.handle(gist("it is late"))
    service.handle(gist("yes please"))
    assert agreed_offer(guard, list(turn.calls[1].history))


def test_a_stuck_worker_makes_new_requests_not_ready() -> None:
    hold = threading.Event()
    turn = FakeTurn(hold=hold)
    service = make_service(turn, total=0.2)
    assert service.handle(gist("slow")).result == Refused("timeout")
    assert service.health().status == "loading"
    quick = FakeTurn()
    service.turn = quick
    assert service.handle(gist("next")).result == Refused("not_ready", LIMITS.retry_after_s)
    assert quick.calls == []
    hold.set()
    for _ in range(int(PATIENCE * 1000)):
        if service.health().status == "ready":
            break
        threading.Event().wait(0.001)
    assert service.health().status == "ready"
