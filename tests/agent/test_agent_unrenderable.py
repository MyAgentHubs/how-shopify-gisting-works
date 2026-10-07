import json
from pathlib import Path

import pytest
from agent_support import (
    QUESTION,
    SECRET,
    SESSION,
    Rig,
    good_call,
    internal_of,
    parcel_order,
    public_of,
    rig,
    rig_with_order,
)
from fakes.shopify import FakeTransport

from gisting.agent.policy import (
    POLICY_FILE,
    AgentPolicyError,
    FallbackReason,
    load_agent_policy,
)
from gisting.prompt.messages import AssistantMessage, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.shopify.client import AdminClient
from gisting.shopify.results import Cause, NotExecuted
from gisting.tools.cache import InMemoryOrderCache
from gisting.tools.lookup_order import LookupDeps, LookupOrder
from gisting.tools.policy import load_policy

POLICY = load_agent_policy()
PHRASES = load_phrases()
REASON = FallbackReason.UNRENDERABLE_ORDER


def run(statuses: list[str | None], estimated: str | None = "2026-10-05T10:00:00Z"):
    subject = rig_with_order(parcel_order(statuses, estimated=estimated), good_call(), "never used")
    return subject, subject.run()


@pytest.mark.parametrize("status", ["CANCELED", "LABEL_PRINTED", "FAILURE", "NOT_DELIVERED"])
def test_a_parcel_in_a_status_without_copy_gets_the_fallback_reply_not_an_invented_line(
    status: str,
) -> None:
    subject, result = run([status])
    assert result.fallback_reason is REASON
    assert result.answer == POLICY.fallback_replies[REASON]
    assert subject.model.outputs == ["never used"]
    assert internal_of(result)["fallback_reason"] == "unrenderable_order"
    assert internal_of(result)["reply_source"] == "fallback"
    assert "has shipped" not in result.answer


def test_one_unknown_parcel_among_several_degrades_the_whole_reply() -> None:
    _, result = run(["IN_TRANSIT", "CANCELED", "DELIVERED"])
    assert result.fallback_reason is REASON
    assert "parcel" not in result.answer


def test_the_fallback_reply_for_an_unrenderable_order_is_the_unavailable_reply_with_its_offer() -> (
    None
):
    reply = POLICY.fallback_replies[REASON]
    assert reply == PHRASES.failure_replies["unavailable"]
    assert reply != POLICY.fallback_replies[FallbackReason.UNCHECKED_CONCLUSION]
    assert reply.endswith(PHRASES.handoff_offer)


def policy_with(tmp_path: Path, reply: object) -> Path:
    document = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    document["fallback_replies"][REASON.value] = reply
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document))
    return path


def test_the_policy_file_points_at_the_unavailable_reply_instead_of_copying_it() -> None:
    document = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    assert document["fallback_replies"][REASON.value] == {"failure_reply": "unavailable"}


@pytest.mark.parametrize("reply", [{"failure_reply": "no_such_reply"}, {"other": "unavailable"}, 7])
def test_a_fallback_reply_that_points_nowhere_is_rejected(tmp_path: Path, reply: object) -> None:
    with pytest.raises(AgentPolicyError):
        load_agent_policy(policy_with(tmp_path, reply))


def test_a_fallback_reply_written_out_is_still_accepted(tmp_path: Path) -> None:
    policy = load_agent_policy(policy_with(tmp_path, "Sorry, try later."))
    assert policy.fallback_replies[REASON] == "Sorry, try later."


def unavailable_subject() -> Rig:
    subject = rig(good_call(), "never used")
    transport = FakeTransport([parcel_order(["IN_TRANSIT"])])
    for _ in range(3):
        transport.fail("order_state", NotExecuted(Cause.NETWORK, "down"))
    client = AdminClient(transport, sleep=lambda _seconds: None)
    deps = LookupDeps(client, InMemoryOrderCache(60), subject.attempts, load_policy(), SECRET)
    subject.tool.inner = LookupOrder(deps)
    return subject


def test_a_real_outage_and_an_unrenderable_order_look_the_same_to_the_customer() -> None:
    outage = unavailable_subject().run()
    _, odd = run(["CANCELED"])
    assert outage.answer == PHRASES.failure_replies["unavailable"]
    assert odd.answer == outage.answer
    assert public_of(odd)["tools"] == public_of(outage)["tools"]
    assert public_of(odd)["tokens"] == public_of(outage)["tokens"]
    assert set(public_of(odd)) == set(public_of(outage))
    assert public_of(odd)["tools"][0]["outcome"] == "unavailable"


def test_an_unrenderable_order_offers_the_handoff_which_a_yes_then_accepts() -> None:
    _, odd = run(["CANCELED"])
    subject = rig()
    subject.run([UserMessage(QUESTION), AssistantMessage(odd.answer), UserMessage("yes")])
    assert subject.handoff.calls == [({"reason": "unavailable"}, SESSION)]


def test_the_public_trace_does_not_say_why_the_order_could_not_be_rendered() -> None:
    _, result = run(["CANCELED"])
    assert "CANCELED" not in str(public_of(result))


@pytest.mark.parametrize("stamp", ["soon", "2026-13-45", "", "05/10/2026"])
def test_a_bad_timestamp_is_not_a_fallback_but_a_parcel_without_a_date(stamp: str) -> None:
    _, result = run(["IN_TRANSIT"], estimated=stamp)
    assert result.fallback_reason is None
    assert result.answer.startswith("Your order is on its way: it is with Test Parcel,")
    assert result.answer.endswith("but I do not have a delivery date yet.")


def test_every_known_status_is_still_rendered_by_code() -> None:
    for status in ("IN_TRANSIT", "OUT_FOR_DELIVERY", "DELAYED", "ATTEMPTED_DELIVERY", "DELIVERED"):
        _, result = run([status])
        assert result.fallback_reason is None
        assert internal_of(result)["reply_source"] == "code"


def test_the_unavailable_policy_search_has_its_own_fallback_name_with_the_same_reply() -> None:
    assert FallbackReason.POLICY_UNAVAILABLE.value == "policy_unavailable"
    assert FallbackReason.POLICY_UNAVAILABLE is not REASON
    assert (
        POLICY.fallback_replies[FallbackReason.POLICY_UNAVAILABLE]
        == (POLICY.fallback_replies[REASON])
    )
    document = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    assert document["fallback_replies"]["policy_unavailable"] == {"failure_reply": "unavailable"}
