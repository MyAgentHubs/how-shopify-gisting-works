import json
import re
from collections import Counter

import pytest
from oracle import last_assistant_text

from gisting.agent.consent import agreed_offer, consent_given, offered, refused_offer
from gisting.agent.policy import load_agent_policy
from gisting.eval.case import FIRST
from gisting.prompt.messages import ToolMessage, UserMessage
from gisting.prompt.phrases import load_phrases
from gisting.training.dataset import build_dataset
from gisting.training.samples import Sample

SAMPLES = build_dataset()
POLICY = load_agent_policy()
PHRASES = load_phrases()
GUARDS = POLICY.consent_guards
HANDOFF_GUARD, REMINDER_GUARD = GUARDS["handoff_to_human"], GUARDS["send_shipping_reminder"]
COUNTS = {
    "handoff_request": (8, 4),
    "handoff_decline": (8, 4),
    "reminder_decline": (6, 3),
}


def of(category: str, split: str | None = None) -> list[Sample]:
    return [s for s in SAMPLES if s.category == category and split in (None, s.split)]


def user_texts(sample: Sample) -> list[str]:
    return [m.content for m in sample.messages if isinstance(m, UserMessage)]


@pytest.mark.parametrize(("category", "counts"), list(COUNTS.items()))
def test_every_multi_turn_category_has_its_planned_size_in_each_split(
    category: str, counts: tuple[int, int]
) -> None:
    assert (len(of(category, "train")), len(of(category, "dev"))) == counts


def test_every_multi_turn_sample_is_graded_on_the_turn_right_after_the_customer_answer() -> None:
    kinds = {c: {s.kind for s in of(c)} for c in COUNTS}
    for category in COUNTS:
        assert kinds[category] == {FIRST}


@pytest.mark.parametrize("category", ["handoff_decline", "reminder_decline"])
def test_the_customer_answers_an_offer_the_agent_really_made(category: str) -> None:
    guard = HANDOFF_GUARD if category.startswith("handoff") else REMINDER_GUARD
    for sample in of(category):
        assert isinstance(sample.messages[-1], UserMessage)
        assert offered(guard, last_assistant_text(sample)), sample.id


@pytest.mark.parametrize("category", ["handoff_decline", "reminder_decline"])
def test_every_decline_or_vague_answer_is_one_the_consent_guard_stops(category: str) -> None:
    guard = HANDOFF_GUARD if category.startswith("handoff") else REMINDER_GUARD
    for sample in of(category):
        assert not consent_given(guard, sample.messages), (sample.id, user_texts(sample)[-1])


def test_every_unprompted_request_for_a_human_is_one_the_consent_guard_lets_through() -> None:
    for sample in of("handoff_request"):
        assert consent_given(HANDOFF_GUARD, sample.messages), (sample.id, user_texts(sample)[-1])


def test_a_request_for_a_human_comes_both_cold_and_after_a_lookup() -> None:
    shapes = Counter(len(sample.messages) for sample in of("handoff_request", "train"))
    assert set(shapes) == {1, 5}
    assert shapes[1] == shapes[5] == 4


def test_the_reminder_samples_are_only_about_unshipped_orders() -> None:
    for category in ("reminder_decline",):
        for sample in of(category):
            result = json.loads(
                next(m.content for m in sample.messages if isinstance(m, ToolMessage))
            )
            assert result["order"]["fulfillment_status"]["value"] == "UNFULFILLED"
            assert PHRASES.sentences["reminder_offer"] in last_assistant_text(sample)


def test_the_handoff_decline_samples_cover_every_scenario_that_offers_a_human_in_train() -> None:
    scenarios = {s.scenario for s in of("handoff_decline", "train")}
    assert scenarios == {
        "ATTEMPTED_DELIVERY",
        "DELAYED",
        "FULFILLED_NO_TRACKING",
        "unavailable",
        "locked",
    }


def test_train_and_dev_share_no_agreement_decline_or_request_wording() -> None:
    for category in COUNTS:
        train = {user_texts(s)[-1] for s in of(category, "train")}
        dev = {user_texts(s)[-1] for s in of(category, "dev")}
        assert not train & dev, category


def test_the_multi_turn_samples_do_not_move_any_existing_sample() -> None:
    plain = [s for s in SAMPLES if s.category not in COUNTS and not re.search(r"-p\d{3}$", s.id)]
    assert len(plain) == 154


@pytest.mark.parametrize("category", ["handoff_decline", "reminder_decline"])
def test_the_vague_replies_that_the_model_still_handles_are_in_every_split(category: str) -> None:
    guard = HANDOFF_GUARD if category.startswith("handoff") else REMINDER_GUARD
    for split in ("train", "dev"):
        vague = [s for s in of(category, split) if not refused_offer(guard, s.messages)]
        assert vague, (category, split)


def test_a_clear_no_never_reaches_the_model_so_the_samples_only_teach_the_vague_ones() -> None:
    clear = [s for s in of("handoff_decline") if refused_offer(HANDOFF_GUARD, s.messages)]
    assert clear
    assert all(not agreed_offer(HANDOFF_GUARD, s.messages) for s in clear)
