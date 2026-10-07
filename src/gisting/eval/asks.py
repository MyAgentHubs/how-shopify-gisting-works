from gisting.eval.data_model import GraderData
from gisting.eval.text import canned_form

BOTH = "both"
EMAIL = "email"
ORDER_NUMBER = "order_number"


def order_tokens(text: str, data: GraderData) -> list[str]:
    return data.inputs.order_token.findall(data.inputs.email_token.sub(" ", text))


def missing_key(text: str, data: GraderData) -> str | None:
    has_email = data.inputs.email_token.search(text) is not None
    has_order = bool(order_tokens(text, data))
    if has_email and has_order:
        return None
    if has_email:
        return ORDER_NUMBER
    return EMAIL if has_order else BOTH


def exact_ask_problems(text: str, written: str, data: GraderData) -> list[str]:
    said = canned_form(text)
    if said in data.ask_bare_sentences:
        return ["ask_lacks_example"]
    chosen = next((key for key, sentence in data.ask_sentences.items() if sentence == said), None)
    if chosen is None:
        shown = any(span.search(text) for span in data.example_spans)
        return (
            ["ask_not_a_fixed_sentence"]
            if shown
            else ["ask_lacks_example", "ask_not_a_fixed_sentence"]
        )
    if chosen != missing_key(written, data):
        return ["asks_for_wrong_item"]
    return []
