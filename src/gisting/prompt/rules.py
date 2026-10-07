from gisting.prompt.files import read_prompt
from gisting.prompt.phrases import ReplyPhrases, load_phrases

RULES_FILE = "system_rules.md"
CALL_REPLY = 'call lookup_order with order_number "{order_number}" and email "{email}"'
STEP_EXAMPLE = 'Customer: "{customer}"\nReply: {reply}'


def call_example_lines(phrases: ReplyPhrases) -> str:
    return "\n".join(
        STEP_EXAMPLE.format(
            customer=example.customer,
            reply=CALL_REPLY.format(order_number=example.order_number, email=example.email),
        )
        for example in phrases.step_examples
    )


def rules_values(phrases: ReplyPhrases) -> dict[str, str]:
    return {
        **phrases.sentences,
        "call_examples": call_example_lines(phrases),
    }


def rules_text(phrases: ReplyPhrases | None = None) -> str:
    return read_prompt(RULES_FILE).format(**rules_values(phrases or load_phrases()))
