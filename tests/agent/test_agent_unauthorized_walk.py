from hypothesis import given, settings
from hypothesis import strategies as st
from walk_support import KINDS, SPELLINGS, Action, Conversation, surface_leaks

NUMBERS = st.sampled_from([1001, 1002, 1003, 1004, 1042, 1100, 1101])
ACTIONS = st.builds(
    Action,
    kind=st.sampled_from(KINDS),
    number=NUMBERS,
    shift=st.integers(1, 100),
    style=st.integers(0, len(SPELLINGS) - 1),
)


@settings(max_examples=250, deadline=None)
@given(walk=st.lists(ACTIONS, min_size=1, max_size=8))
def test_no_turn_of_any_conversation_shows_data_of_an_order_it_did_not_verify(
    walk: list[Action],
) -> None:
    conversation = Conversation()
    authorized: set[str] = set()
    for action in walk:
        document, found = conversation.turn(action.text, action.outputs)
        still_discussed = action.named is None or action.named in authorized
        authorized = found | (authorized if still_discussed else set())
        assert surface_leaks(document, conversation.prompts(), authorized) == []
