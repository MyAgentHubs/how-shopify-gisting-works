import json

from agent_support import SECRET, SESSION, demo_order, rig_with_orders, tool_call
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.shopify.demo_email import demo_email

ORDERS = st.integers(1001, 1101)
OPENERS = (
    "Where is order #{n}? My email is {email}",
    "{email} - any news on {n}?",
    "hi, #{n} / {email}, when does it arrive",
    "ORDER {n}\nEmail: {email}\nwhere is it",
)
FOLLOW_UPS = (
    "And order #{n}? My email is {email}",
    "What about #{n}? {email}",
    "can you also check {n}",
    "now #{n} please",
    "No.{n} then {email}",
    "order_{n} {email}",
    "is order {n} items shipped",
)
ALL_ORDERS = [demo_order(number) for number in range(1001, 1102)]


def email_of(number: int) -> str:
    return demo_email(SECRET, f"#{number}")


def secrets_of(number: int) -> tuple[str, ...]:
    return (email_of(number), f"TP-{number}", f"GLR-{number:08X}", f"#{number}")


def history_text(subject_prompt: str) -> str:
    return subject_prompt.rsplit("</tools>", 1)[1]


@settings(max_examples=150, deadline=None)
@given(
    first=ORDERS,
    second=ORDERS,
    opener=st.sampled_from(OPENERS),
    follow_up=st.sampled_from(FOLLOW_UPS),
    ask_email_again=st.booleans(),
)
def test_a_question_about_order_b_never_puts_order_a_in_the_model_input(
    first: int, second: int, opener: str, follow_up: str, ask_email_again: bool
) -> None:
    assume(first != second)
    call_a = tool_call(order_number=f"#{first}", email=email_of(first))
    opening = opener.format(n=first, email=email_of(first))
    turn_one = rig_with_orders(ALL_ORDERS, call_a).run([UserMessage(opening)])
    email_b = email_of(second) if ask_email_again else ""
    question = follow_up.format(n=second, email=email_b)
    history: list[Message] = [UserMessage(opening), AssistantMessage(turn_one.answer)]
    history.append(UserMessage(question))
    model_sees_b = tool_call(order_number=f"#{second}", email=email_of(second))
    subject = rig_with_orders(ALL_ORDERS, model_sees_b, "unused")
    result = subject.run(history)
    seen = history_text(subject.prompt_text(0))
    for secret in secrets_of(first):
        assert secret not in seen
        assert secret not in result.answer
        assert secret not in json.dumps(result.traces.public)
    if not ask_email_again:
        assert subject.tool.calls == []
        assert all(secret not in result.answer for secret in secrets_of(first))
    for arguments, session in subject.tool.calls:
        assert session == SESSION
        assert arguments["order_number"] == f"#{second}"
