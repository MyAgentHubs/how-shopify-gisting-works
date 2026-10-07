import pytest
from test_agent_consent_whitelist import ALL_OFFERS, after, guard_for

from gisting.agent.consent import agreed_offer, consent_given, refused_offer

KEPT = ["yes!", "Yes, please.", "ok.", "yes - please", "yes 👍", "yes…", "“yes”"]
SYMBOL_OR_QUESTION = [
    "ok 🙄",
    "yes 👎",
    "yes ❌",
    "yes؟",
    "yes‽",
    "yes⁇",
    "yes¿",
    "yes﹖",
    "yes❓",
    "yes❔",
    "yes ✅ no",
    "yes ~",
    "yes_",
    "yes (please)",
]


@pytest.mark.parametrize("name", list(ALL_OFFERS))
@pytest.mark.parametrize("reply", KEPT)
def test_small_punctuation_around_a_yes_is_still_a_yes(name: str, reply: str) -> None:
    assert agreed_offer(guard_for(name), after(ALL_OFFERS[name], reply))


@pytest.mark.parametrize("name", list(ALL_OFFERS))
@pytest.mark.parametrize("reply", SYMBOL_OR_QUESTION)
def test_any_other_symbol_or_a_question_mark_in_any_script_is_not_a_yes(
    name: str, reply: str
) -> None:
    history = after(ALL_OFFERS[name], reply)
    assert not agreed_offer(guard_for(name), history)
    assert not consent_given(guard_for(name), history)


@pytest.mark.parametrize("name", list(ALL_OFFERS))
@pytest.mark.parametrize("reply", ["no ❌", "no 🙄", "no 👍"])
def test_a_no_followed_by_an_emoji_stays_a_clear_no(name: str, reply: str) -> None:
    assert refused_offer(guard_for(name), after(ALL_OFFERS[name], reply))
