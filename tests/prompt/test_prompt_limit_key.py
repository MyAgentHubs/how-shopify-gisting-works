import json

from replies_support import detailed, found

from gisting.prompt.phrases import PHRASES_FILE, ReplyPhrases, parse_phrases
from gisting.prompt.replies import fixed_reply


def listing_from_one(line: str) -> ReplyPhrases:
    document = json.loads(PHRASES_FILE.read_text(encoding="utf-8"))
    document["limits"]["several_parcels_from_by_line"] = {line: 1}
    return parse_phrases(json.dumps(document))


def test_a_parcel_status_as_the_per_line_key_does_not_change_how_a_fulfilled_order_is_listed() -> (
    None
):
    phrases = listing_from_one("IN_TRANSIT")
    text = fixed_reply(phrases, found("FULFILLED", detailed("IN_TRANSIT")))
    assert text.startswith("Your order ")
