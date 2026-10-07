from hypothesis import assume, given, settings
from hypothesis import strategies as st
from tool_support import (
    FIRST_ORDER,
    LAST_ORDER,
    Harness,
    demo_orders,
    email_for,
    harness,
    public_wire,
)

HOMOGLYPHS = {"a": "а", "e": "е", "o": "о", "c": "с", "p": "р", "x": "х"}
KINDS = (
    "empty",
    "upper",
    "plus",
    "homoglyph",
    "prefix",
    "suffix",
    "local_only",
    "domain_only",
    "leading_space",
    "trailing_space",
    "newline",
    "nul",
    "appended",
    "prepended",
    "other_order",
    "free_text",
)
ORDERS = st.integers(FIRST_ORDER, LAST_ORDER)


def homoglyph(email: str) -> str:
    for index, char in enumerate(email):
        if char in HOMOGLYPHS:
            return email[:index] + HOMOGLYPHS[char] + email[index + 1 :]
    return email


def wrong_email(number: int, kind: str, text: str, cut: int) -> str:
    email = email_for(number)
    local, _, domain = email.partition("@")
    variants = {
        "empty": "",
        "upper": email.upper(),
        "plus": f"{local}+demo@{domain}",
        "homoglyph": homoglyph(email),
        "prefix": email[: max(cut, 1) % len(email)],
        "suffix": email[max(cut, 1) % len(email) :],
        "local_only": local,
        "domain_only": domain,
        "leading_space": f" {email}",
        "trailing_space": f"{email} ",
        "newline": f"{email}\n",
        "nul": f"{email}\x00",
        "appended": email + text,
        "prepended": text + email,
        "other_order": email_for(FIRST_ORDER + (number - FIRST_ORDER + 1) % 101),
        "free_text": text,
    }
    return variants[kind]


def serialized(env: Harness, number: int, email: str) -> str:
    return public_wire(env.lookup(f"#{number}", email))


@settings(max_examples=400, deadline=None)
@given(
    number=ORDERS,
    kind=st.sampled_from(KINDS),
    text=st.text(max_size=12),
    cut=st.integers(0, 40),
)
def test_wrong_email_output_equals_order_does_not_exist_output(
    number: int, kind: str, text: str, cut: int
) -> None:
    email = wrong_email(number, kind, text, cut)
    assume(email != email_for(number))
    existing = harness(*demo_orders())
    absent = harness()
    guessed = existing.lookup(f"#{number}", email)
    nonexistent = absent.lookup(f"#{number}", email_for(number))
    assert guessed.trace.internal.result_type == "Mismatch"
    assert nonexistent.trace.internal.result_type == "NotFound"
    assert public_wire(guessed) == public_wire(nonexistent)
    assert public_wire(guessed) == serialized(absent, number, email)
    assert existing.fake.calls == []
    assert existing.cache.gets == []
    assert existing.cache.puts == []


@settings(max_examples=200, deadline=None)
@given(number=ORDERS, text=st.text(max_size=24))
def test_arbitrary_text_never_unlocks_an_order(number: int, text: str) -> None:
    assume(text != email_for(number))
    env = harness(*demo_orders())
    response = env.lookup(f"#{number}", text)
    assert response.result["status"] == "no_match"
    assert env.fake.calls == []


def test_every_demo_order_matches_only_its_own_email() -> None:
    env = harness(*demo_orders())
    for number in range(FIRST_ORDER, LAST_ORDER + 1):
        right = env.lookup(f"#{number}", email_for(number), session_id=f"s{number}")
        wrong = env.lookup(f"#{number}", email_for(number).upper(), session_id=f"w{number}")
        assert right.result["status"] == "found"
        assert wrong.result["status"] == "no_match"


def test_model_result_is_identical_for_every_kind_of_no_match() -> None:
    env = harness(*demo_orders())
    absent = harness()
    results = [
        env.lookup("garbage", "x").result,
        env.lookup("#9999", email_for(1042)).result,
        env.lookup("#1042", "x").result,
        env.lookup("#1042", "").result,
        absent.lookup("#1042", email_for(1042)).result,
    ]
    assert all(result == results[0] for result in results)
    assert results[0] == {"status": "no_match"}
