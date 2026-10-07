from gisting.agent.policy import INVALID_STATUS
from gisting.prompt.rules import rules_text


def test_the_rules_only_tell_the_model_what_to_do_with_a_rejected_call() -> None:
    rules = rules_text()
    assert INVALID_STATUS in rules
    for status in ("no_match", "unavailable", "locked", "handed_off", "requested"):
        assert status not in rules


def test_the_rules_never_ask_the_model_to_follow_a_message_field() -> None:
    assert "message field" not in rules_text()
