import re
import unicodedata
from collections.abc import Mapping

from gisting.eval.case import Case
from gisting.eval.data_model import GraderData
from gisting.eval.first_turn_tools import tool_call_problems
from gisting.eval.source import Source
from gisting.prompt.messages import UserMessage
from gisting.prompt.parse import ParsedOutput

QUERY_KEY = "query"
WORD = re.compile(r"[a-z0-9]+")
MENTION = re.compile(r"(#?)(\d+)")
SEPARATOR = " "
NORMAL_FORM = "NFKC"


def plain(text: str) -> str:
    return unicodedata.normalize(NORMAL_FORM, text)


def words_of(text: str) -> tuple[str, ...]:
    return tuple(WORD.findall(plain(plain(text).casefold()).lower()))


def search_words(query: str, data: GraderData) -> tuple[str, ...]:
    kept = (word for word in words_of(query) if word not in data.policy.query.stopwords)
    return tuple(dict.fromkeys(kept))


def written_orders(text: str, data: GraderData) -> list[str]:
    rules = data.policy.query
    mentions = MENTION.findall(rules.email.sub(SEPARATOR, plain(text)))
    return [
        digits
        for hashed, digits in mentions
        if len(digits) <= data.limits.order_digits_max
        and (hashed or rules.order_min <= int(digits) <= rules.order_max)
    ]


def latest_customer_text(case: Case) -> str:
    said = [m.content for m in case.messages if isinstance(m, UserMessage)]
    return said[-1] if said else ""


def shape_problems(query: str, data: GraderData) -> list[str]:
    rules = data.policy.query
    found = ["query_too_long"] if len(query) > rules.max_chars else []
    return [
        *found,
        *(["query_too_many_terms"] if len(search_words(query, data)) > rules.max_terms else []),
    ]


def term_problems(query: str, said: str, data: GraderData) -> list[str]:
    if not words_of(query):
        return ["empty_query"]
    wanted = search_words(query, data)
    if not wanted:
        return ["query_only_filler_words"]
    unsaid = sorted(set(wanted) - set(words_of(said)))
    return [f"query_term_not_said:{','.join(unsaid)}"] if unsaid else []


def query_problems(query: str, said: str, data: GraderData) -> list[str]:
    found = shape_problems(query, data)
    if any(data.policy.query.email.search(view) for view in (query, plain(query))):
        found.append("query_has_email")
    if written_orders(query, data):
        found.append("query_has_order_number")
    return [*found, *term_problems(query, said, data)]


def search_argument_problems(
    case: Case, arguments: Mapping[str, object], data: GraderData
) -> list[str]:
    found = ["unexpected_arguments"] if frozenset(arguments) != data.policy.arguments else []
    said = latest_customer_text(case)
    if written_orders(said, data):
        found.append("order_number_in_message")
    query = arguments.get(QUERY_KEY)
    if not isinstance(query, str):
        return [*found, "query_not_a_string"] if QUERY_KEY in arguments else found
    return [*found, *query_problems(query, said, data)]


def search_call_problems(
    case: Case, parsed: ParsedOutput, source: Source, data: GraderData
) -> list[str]:
    return tool_call_problems(
        parsed,
        source,
        data,
        data.policy.tool,
        lambda args: search_argument_problems(case, args, data),
    )
