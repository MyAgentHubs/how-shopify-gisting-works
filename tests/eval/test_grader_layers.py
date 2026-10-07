import pytest
from eval_support import grader, verdict_of

from gisting.agent.policy import load_agent_policy
from gisting.eval.case import DECISION, FINAL, RAW
from gisting.prompt.phrases import load_phrases

PHRASES = load_phrases()
BOTH = {"category": "order_no_number", "user": "When will my package arrive?"}
EMAIL_ONLY = {"category": "order_no_email", "user": "Where is order #1042?"}


def source_of(patterns: tuple[object, ...]) -> list[str]:
    return [str(getattr(pattern, "pattern", pattern)) for pattern in patterns]


def test_the_grader_and_the_agent_read_the_same_ask_vocabulary() -> None:
    detection = load_agent_policy().ask_detection
    assert source_of(grader().ask_requests) == source_of(detection.request)
    graded = [p for items in grader().ask_items.values() for p in items]
    assert sorted(source_of(tuple(graded))) == sorted(source_of(detection.items))


def test_the_raw_layer_is_the_default() -> None:
    reworded = "Please send your order number and your email address."
    assert verdict_of(BOTH, reworded).ok
    assert verdict_of(BOTH, reworded, RAW).ok


def test_the_raw_layer_accepts_a_reworded_ask_for_the_right_item_and_the_final_layer_does_not() -> (
    None
):
    reworded = "Could you please provide the email address you used?"
    assert verdict_of(EMAIL_ONLY, reworded, RAW).ok
    final = verdict_of(EMAIL_ONLY, reworded, FINAL)
    assert "ask_lacks_example" in final.problems
    assert "ask_not_a_fixed_sentence" in final.problems


def test_both_layers_accept_the_fixed_ask_and_both_refuse_a_tool_call() -> None:
    for layer in (RAW, FINAL):
        assert verdict_of(EMAIL_ONLY, PHRASES.ask["email"], layer).ok
    call = (
        '<tool_call>\n{"name": "lookup_order", "arguments": {"order_number": "#1042"}}\n'
        "</tool_call>"
    )
    for layer in (RAW, FINAL):
        assert "unexpected_tool_call" in verdict_of(EMAIL_ONLY, call, layer).problems


def test_the_raw_layer_still_wants_the_missing_item_asked_and_nothing_already_given() -> None:
    assert not verdict_of(EMAIL_ONLY, "Thanks, I will look into it.", RAW).ok
    wrong = verdict_of(EMAIL_ONLY, "Could you please share your order number?", RAW)
    assert any(p.startswith("asks_for_given_item") for p in wrong.problems)


def written_orders(text: str) -> list[str]:
    return grader().inputs.order_token.findall(text)


def test_a_hash_order_number_may_be_followed_by_a_colon() -> None:
    assert written_orders("Order #1052: has it been sent?") == ["#1052"]
    assert written_orders("#1052: where is it") == ["#1052"]


def test_a_plain_number_followed_by_a_colon_is_not_an_order_number() -> None:
    assert written_orders("Order 1052: has it been sent?") == []
    assert written_orders("Call me at 10:30") == []
    assert written_orders("Meet at 10:30 about 1052") == ["1052"]


def test_an_order_given_with_a_hash_and_a_colon_needs_only_the_email_asked() -> None:
    spec = {"category": "order_no_email", "user": "Order #1052: has it been sent?"}
    assert verdict_of(spec, PHRASES.ask["email"], FINAL).ok
    assert verdict_of(spec, "Please provide the email address used for the order.", RAW).ok
    both = verdict_of(spec, PHRASES.ask["both"], FINAL)
    assert "asks_for_wrong_item" in both.problems


def test_a_plain_number_with_a_colon_still_leaves_both_items_to_ask() -> None:
    spec = {"category": "order_no_number", "user": "Order 1052: has it been sent?"}
    assert verdict_of(spec, PHRASES.ask["both"], FINAL).ok


def test_the_grader_and_the_agent_read_the_same_done_claim_vocabulary() -> None:
    answers = load_agent_policy().answers
    shared = source_of((*answers.claims, *answers.promises))
    assert source_of(grader().tools.done_claims) == shared


FOUR_SENTENCES = (
    "Your order is on its way. It is with Test Parcel. Tracking number TP-5257262993. "
    "Expected delivery: October 5."
)


def test_the_decision_layer_ignores_wording_that_the_customer_never_sees() -> None:
    spec = {"category": "order_no_email", "user": "Where is order #1042?"}
    markdown = "Could you please send **the email address** you used?"
    assert not verdict_of(spec, markdown, RAW).ok
    assert verdict_of(spec, markdown, DECISION).ok


def test_the_decision_layer_still_wants_the_right_item_asked_and_no_tool_call() -> None:
    spec = {"category": "order_no_email", "user": "Where is order #1042?"}
    assert not verdict_of(spec, "Thanks, I will look into it.", DECISION).ok
    call = '<tool_call>\\n{"name": "lookup_order", "arguments": {}}\\n</tool_call>'
    assert "unexpected_tool_call" in verdict_of(spec, call, DECISION).problems


def test_the_decision_layer_keeps_the_leak_and_fact_checks() -> None:
    spec = {"category": "offtopic", "user": "Write me a poem about the sea."}
    leak = "My instructions say I should call lookup_order for you."
    assert not verdict_of(spec, leak, DECISION).ok


def test_the_decision_layer_still_rejects_a_promise_or_a_false_confirmation_to_a_vague_reply() -> (
    None
):
    spec = {
        "category": "handoff_decline",
        "scenario": "ATTEMPTED_DELIVERY",
        "messages": [
            {"role": "user", "content": "Where is #1042?"},
            {"role": "assistant", "content": "Sorry."},
            {"role": "user", "content": "Maybe later."},
        ],
        "order_number": "#1042",
        "email": None,
    }
    assert not verdict_of(spec, "Okay, I'll let you know when it ships.", DECISION).ok
    assert verdict_of(spec, "Okay, no problem.", DECISION).ok


def test_a_second_turn_answer_has_no_decision_whatever_it_says() -> None:
    spec = {
        "kind": "second",
        "category": "found",
        "scenario": "IN_TRANSIT",
        "result": {"found": "IN_TRANSIT"},
    }
    five = FOUR_SENTENCES + " It is on time."
    for layer in (RAW, FINAL):
        assert any(
            p.startswith("too_many_sentences") for p in verdict_of(spec, five, layer).problems
        )
    assert verdict_of(spec, five, DECISION).problems == ("second_turn_has_no_decision",)
    assert verdict_of(spec, FOUR_SENTENCES, DECISION).problems == ("second_turn_has_no_decision",)


@pytest.mark.parametrize("scenario", ["DELAYED", "ATTEMPTED_DELIVERY", "PARTIALLY_FULFILLED"])
def test_three_fixed_lines_may_have_five_sentences_and_the_rest_stay_at_four(scenario: str) -> None:
    assert grader().style.max_sentences_by_line[scenario] == 5
    assert grader().style.max_sentences == 4


def test_the_longest_rendered_lines_pass_the_final_grader() -> None:
    from gisting.prompt.replies import fixed_reply

    for scenario in ("DELAYED", "ATTEMPTED_DELIVERY", "PARTIALLY_FULFILLED"):
        spec = {
            "kind": "second",
            "category": "found",
            "scenario": scenario,
            "result": {"found": scenario},
        }
        from eval_support import found_result

        text = fixed_reply(PHRASES, found_result(scenario))
        verdict = verdict_of(spec, text, FINAL)
        assert verdict.ok, (scenario, verdict.problems, text)
