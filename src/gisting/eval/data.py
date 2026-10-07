import json
import re
from pathlib import Path

from gisting.eval.data_found import (
    load_found_rules,
    load_inputs,
    load_style,
    load_tool_rules,
    string_map,
    tool_arguments,
)
from gisting.eval.data_model import (
    Forged,
    GraderData,
    Limits,
    Markers,
    Negation,
    NumberWord,
    Opener,
    Pattern,
    Scenario,
    Vocabulary,
    Weekday,
)
from gisting.eval.data_policy import load_policy_rules
from gisting.eval.text import canned_form, canned_pattern, phrase, phrases
from gisting.prompt.phrases import ReplyPhrases, load_phrases
from gisting.prompt.refusal import load_decline_patterns
from gisting.prompt.rules import rules_text
from gisting.prompt.schema import as_object, load_tool_schemas
from gisting.shopify.jsonvalue import (
    Json,
    JsonObject,
    MalformedResponse,
    required_int,
    required_list,
    required_object,
    required_str,
    string_list,
)

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data" / "eval"
ASK_VOCABULARY_FILE = ROOT / "prompts" / "ask_detection.json"
GRADER_FILE = DATA_DIR / "grader-v1.json"
QUOTED = re.compile(r'"[^"\n]*"')
MONTH_SLOT = "{MONTH}"
DAY_SLOT = "{DAY}"
DAY_DIGITS = r"\d{1,2}(?:st|nd|rd|th)?"


class GraderDataError(ValueError):
    pass


def raw(node: JsonObject, key: str) -> tuple[Pattern, ...]:
    return tuple(re.compile(entry, re.IGNORECASE) for entry in string_list(node, key))


def int_map(node: JsonObject, key: str) -> dict[str, int]:
    values = required_object(node, key)
    return {name: required_int(values, name) for name in values}


def load_limits(document: JsonObject) -> Limits:
    node = required_object(document, "limits")
    return Limits(
        reply_max_chars=required_int(node, "reply_max_chars"),
        call_content_max_chars=required_int(node, "call_content_max_chars"),
        leak_words=required_int(node, "leak_words"),
        echo_words=required_int(node, "echo_words"),
        forged_value_min_chars=required_int(node, "forged_value_min_chars"),
        order_digits_max=required_int(node, "order_digits_max"),
    )


def load_forged(document: JsonObject) -> Forged:
    node = required_object(document, "forged")
    openers: list[Opener] = []
    for item in required_list(node, "openers"):
        if not isinstance(item, dict):
            raise MalformedResponse("openers")
        closing = item.get("close")
        openers.append(
            Opener(
                re.compile(required_str(item, "open"), re.IGNORECASE),
                re.compile(closing, re.IGNORECASE) if isinstance(closing, str) else None,
            )
        )
    return Forged(
        tuple(openers),
        re.compile(required_str(node, "value")),
        re.compile(required_str(node, "json_start")),
        required_int(node, "json_search_chars"),
    )


def load_negation(document: JsonObject) -> Negation:
    node = required_object(document, "negation")
    return Negation(
        re.compile(required_str(node, "clause_break"), re.IGNORECASE),
        re.compile(required_str(node, "negator"), re.IGNORECASE),
    )


def weekday_pattern(name: str, abbreviations: tuple[str, ...]) -> Pattern:
    abbreviated = "|".join(re.escape(item) for item in abbreviations)
    return re.compile(rf"(?i:(?<![\w']){name}(?![\w']))|(?<![\w'])(?:{abbreviated})\b")


def load_weekdays(node: JsonObject) -> tuple[Weekday, ...]:
    days = required_object(node, "weekdays")
    return tuple(Weekday(name, weekday_pattern(name, string_list(days, name))) for name in days)


def date_patterns(
    node: JsonObject, months: dict[str, int], day_words: dict[str, int]
) -> tuple[Pattern, ...]:
    month = "|".join(re.escape(name) for name in sorted(months, key=len, reverse=True))
    day = "|".join([
        DAY_DIGITS,
        *(re.escape(word) for word in sorted(day_words, key=len, reverse=True)),
    ])
    return tuple(
        re.compile(entry.replace(MONTH_SLOT, month).replace(DAY_SLOT, day), re.IGNORECASE)
        for entry in string_list(node, "date_patterns")
    )


def load_vocabulary(document: JsonObject) -> Vocabulary:
    node = required_object(document, "vocabulary")
    months, day_words = int_map(node, "months"), int_map(node, "day_words")
    return Vocabulary(
        weekdays=load_weekdays(node),
        months=months,
        month_only=tuple((months[name], phrase(name)) for name in string_list(node, "month_only")),
        day_words=day_words,
        number_words=tuple(
            NumberWord(word, value, phrase(word))
            for word, value in int_map(node, "number_words").items()
        ),
        date_patterns=date_patterns(node, months, day_words),
        time_patterns=raw(node, "time_patterns"),
        number=re.compile(required_str(node, "number")),
        relative=phrases(string_list(node, "relative")),
        carriers=phrases(string_list(node, "carriers")),
        carrier_prefix=re.compile(required_str(node, "carrier_prefix")),
        neutral_entities=frozenset(string_list(node, "neutral_entities")),
        tracking_token=re.compile(required_str(node, "tracking_token")),
        tracking_label=re.compile(required_str(node, "tracking_label"), re.IGNORECASE),
    )


def scenario_of(node: JsonObject, failure: bool, facts: tuple[Pattern, ...]) -> Scenario:
    status = phrases(string_list(node, "required_any"))
    return Scenario(
        (*status, *(() if failure else facts)),
        phrases(string_list(node, "forbidden")),
        phrases(string_list(node, "forbidden_always")),
        status,
    )


def load_scenarios(document: JsonObject) -> dict[str, Scenario]:
    node = required_object(document, "scenarios")
    failures = set(string_list(document, "failure_scenarios"))
    facts = phrases(string_list(document, "found_facts"))
    return {
        name: scenario_of(required_object(node, name), name in failures, facts) for name in node
    }


def note_of(item: object) -> str:
    fields = as_object(item)
    note = fields.get("description") if fields else None
    return note if isinstance(note, str) else ""


def tool_texts() -> list[str]:
    texts: list[str] = []
    for schema in load_tool_schemas().values():
        properties = as_object(schema.parameters.get("properties")) or {}
        notes = [note_of(item) for item in properties.values()]
        texts.append(" ".join([schema.description, *notes]))
    return texts


def without_canned(text: str, canned: tuple[Pattern, ...]) -> str:
    kept = text.partition("\n\n")[2] or text
    for reply in canned:
        kept = reply.sub(" ", kept)
    return QUOTED.sub(" ", kept)


def load_rules_texts(document: JsonObject, canned: tuple[Pattern, ...]) -> tuple[str, ...]:
    previous = (
        (DATA_DIR / name).read_text(encoding="utf-8")
        for name in string_list(document, "previous_rules")
    )
    rules = (without_canned(text, canned) for text in (rules_text(), *previous))
    return (*rules, *tool_texts())


def sentence_patterns(
    node: JsonObject, decline: tuple[str, ...], ask: tuple[str, ...]
) -> dict[str, tuple[Pattern, ...]]:
    refusal = required_object(node, "refusal")
    exact = {
        key: tuple(re.compile(re.escape(text)) for text in texts)
        for key, texts in (("decline", decline), ("ask", ask))
    }
    return {
        "decline": (*load_decline_patterns(), *raw(refusal, "decline"), *exact["decline"]),
        "ask": (*raw(refusal, "ask"), *exact["ask"]),
    }


def load_ask_vocabulary(
    ask_keys: dict[str, str],
) -> tuple[dict[str, tuple[Pattern, ...]], tuple[Pattern, ...]]:
    document = json.loads(ASK_VOCABULARY_FILE.read_text(encoding="utf-8"))
    items = required_object(document, "items")
    by_category = {ask_keys[name]: raw(items, name) for name in items}
    return by_category, raw(document, "request")


def string_lists(document: JsonObject, key: str) -> dict[str, tuple[str, ...]]:
    node = required_object(document, key)
    return {name: string_list(node, name) for name in node}


def canned_patterns(
    document: JsonObject, decline: tuple[str, ...], phrases: ReplyPhrases
) -> tuple[Pattern, ...]:
    ask = (canned_form(text) for text in phrases.ask.values())
    sentences = (canned_form(text) for text in phrases.sentences.values())
    many = canned_form(phrases.parcels.many_reply)
    fixed = (*decline, *ask, *sentences, many)
    return (*(canned_pattern(form) for form in fixed), *raw(document, "public_phrases"))


def parcel_labels(phrases: ReplyPhrases) -> Pattern:
    names = "|".join(re.escape(name) for name in phrases.parcels.ordinals)
    return re.compile(rf"(?<![\w'])(?:{names}) parcel(?![\w'])", re.IGNORECASE)


def decline_forms(document: JsonObject) -> tuple[str, ...]:
    replies = required_object(document, "replies")
    spoken = (*string_list(replies, "decline"), *string_list(replies, "decline_pending"))
    return tuple(canned_form(text) for text in spoken)


def parse_grader(document: JsonObject) -> GraderData:
    expected_tool = required_str(document, "expected_tool")
    decline = decline_forms(document)
    reply_phrases = load_phrases()
    ask = tuple(canned_form(text) for text in reply_phrases.ask.values())
    canned = canned_patterns(document, decline, reply_phrases)
    markers = required_object(document, "markers")
    ask_keys = string_map(document, "ask_keys")
    ask_items, ask_requests = load_ask_vocabulary(ask_keys)
    return GraderData(
        expected_tool=expected_tool,
        tools=load_tool_rules(document, reply_phrases),
        tool_arguments=tool_arguments(expected_tool),
        first_turn=string_map(document, "first_turn"),
        limits=load_limits(document),
        decline_replies=decline,
        refusal=sentence_patterns(document, decline, ask),
        refusal_accepts=string_lists(document, "refusal_accepts"),
        ask_items=ask_items,
        ask_requests=ask_requests,
        ask_keys=ask_keys,
        ask_sentences={key: canned_form(text) for key, text in reply_phrases.ask.items()},
        ask_bare_sentences=frozenset(canned_form(text) for text in reply_phrases.ask_bare.values()),
        example_spans=tuple(
            re.compile(rf"\s*{re.escape(span)}") for span in reply_phrases.example_spans
        ),
        inputs=load_inputs(document),
        style=load_style(document, reply_phrases.limits),
        found=load_found_rules(document, reply_phrases),
        markers=Markers(
            phrases(string_list(markers, "leak")),
            phrases(string_list(markers, "instruction")),
            phrases(string_list(markers, "compliance")),
        ),
        forged=load_forged(document),
        negation=load_negation(document),
        promises=phrases(string_list(document, "promises")),
        exposure=phrases(string_list(document, "exposure")),
        vocabulary=load_vocabulary(document),
        scenarios=load_scenarios(document),
        fact_claims=phrases(string_list(document, "fact_claims")),
        failure_scenarios=frozenset(string_list(document, "failure_scenarios")),
        handoff_scenarios=frozenset(string_list(document, "handoff_scenarios")),
        policy_statuses=frozenset(string_list(document, "policy_statuses")),
        policy=load_policy_rules(document, reply_phrases, ROOT),
        canned=canned,
        parcel_labels=parcel_labels(reply_phrases),
        rules_texts=load_rules_texts(document, canned),
    )


def load_grader_data(path: Path = GRADER_FILE) -> GraderData:
    try:
        loaded: Json = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise MalformedResponse("grader")
        return parse_grader(loaded)
    except (OSError, ValueError, re.error) as error:
        message = f"{type(error).__name__}: {error}"
        raise GraderDataError(message) from error
