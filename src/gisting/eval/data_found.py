import json
import re

from gisting.eval.data_model import FoundRules, Inputs, Pattern, Style, ToolRules
from gisting.eval.text import canned_form, phrases
from gisting.prompt.files import PROMPTS_DIR
from gisting.prompt.parcel_copy import ReplyLimits
from gisting.prompt.phrases import ReplyPhrases
from gisting.prompt.schema import as_object, load_tool_schemas
from gisting.shopify.jsonvalue import (
    JsonObject,
    required_int,
    required_object,
    required_str,
    string_list,
)

DONE_CLAIMS_FILE = PROMPTS_DIR / "done_claims.json"


def folded(node: JsonObject, key: str) -> tuple[Pattern, ...]:
    return tuple(re.compile(entry, re.IGNORECASE) for entry in string_list(node, key))


def lowered(words: dict[str, str]) -> dict[str, str]:
    return {name: phrase.lower() for name, phrase in words.items()}


def load_inputs(document: JsonObject) -> Inputs:
    node = required_object(document, "inputs")
    return Inputs(
        re.compile(required_str(node, "email_token")),
        re.compile(required_str(node, "order_token")),
    )


def load_style(document: JsonObject, limits: ReplyLimits) -> Style:
    node = required_object(document, "style")
    return Style(
        max_sentences=limits.max_sentences,
        max_sentences_by_line=dict(limits.max_sentences_by_line),
        several_parcels_from=limits.several_parcels_from,
        several_parcels_from_by_line=dict(limits.several_parcels_from_by_line),
        max_parcels=limits.max_parcels,
        max_words_per_sentence=required_int(node, "max_words_per_sentence"),
        sentence_break=re.compile(required_str(node, "sentence_break")),
        markdown=folded(node, "markdown"),
        enum_name=re.compile(required_str(node, "enum_name")),
        enum_value=re.compile(required_str(node, "enum_value")),
        readable_date_forbidden=folded(node, "readable_date_forbidden"),
    )


def load_found_rules(document: JsonObject, replies: ReplyPhrases) -> FoundRules:
    node = required_object(document, "found")
    return FoundRules(
        status_anywhere_lines=frozenset(string_list(node, "status_anywhere_lines")),
        handoff_lines=frozenset(string_list(node, "handoff_lines")),
        handoff_untracked_lines=frozenset(string_list(node, "handoff_untracked_lines")),
        reassurance_lines=frozenset(string_list(node, "reassurance_lines")),
        reminder_lines=frozenset(string_list(node, "reminder_lines")),
        no_thanks_lines=frozenset(string_list(node, "no_thanks_lines")),
        partial_status=required_str(node, "partial_status"),
        forbidden_words=phrases(string_list(node, "forbidden_words")),
        empathy=frozenset(canned_form(text) for text in replies.empathy),
        reassurance=canned_form(replies.sentences["no_shipment_details"]),
        reminder_offer=canned_form(replies.sentences["reminder_offer"]),
        thanks=canned_form(replies.sentences["thanks_patience"]),
        unshipped_rest=phrases(string_list(node, "unshipped_rest")),
        invented_reason=phrases(string_list(node, "invented_reason")),
        handoff=phrases(string_list(node, "handoff")),
        contact_carrier=phrases(string_list(node, "contact_carrier")),
        no_estimate_words=phrases(string_list(node, "no_estimate_words")),
        estimate_markers=phrases(string_list(node, "estimate_markers")),
        marker_window_words=required_int(node, "marker_window_words"),
        no_tracking=folded(node, "no_tracking"),
        no_date=folded(node, "no_date"),
        unfilled_slot=re.compile(required_str(node, "unfilled_slot")),
        single_parcel_lines=frozenset(string_list(node, "single_parcel_lines")),
        parcel_scenarios=string_map(node, "parcel_scenarios"),
        many_parcels_reply=canned_form(replies.parcels.many_reply),
        fulfillment_words=lowered(replies.fulfillment_status),
        status_alternatives=alternatives(node, "status_alternatives"),
        transport_words=lowered(replies.transport_status),
        parcel_words=lowered(replies.parcels.status),
        delivered_status=required_str(node, "delivered_status"),
        closing_when={
            status: frozenset(names) for status, names in replies.parcels.closing_when.items()
        },
    )


def alternatives(node: JsonObject, key: str) -> dict[str, tuple[str, ...]]:
    values = required_object(node, key)
    return {name: tuple(text.lower() for text in string_list(values, name)) for name in values}


def string_map(node: JsonObject, key: str) -> dict[str, str]:
    values = required_object(node, key)
    return {name: required_str(values, name) for name in values}


def tool_arguments(tool: str) -> frozenset[str]:
    return frozenset(as_object(load_tool_schemas()[tool].parameters.get("properties")) or {})


def load_tool_rules(document: JsonObject, replies: ReplyPhrases) -> ToolRules:
    tools = string_map(document, "tools")
    claims = json.loads(DONE_CLAIMS_FILE.read_text(encoding="utf-8"))
    return ToolRules(
        handoff_tool=tools["handoff"],
        reminder_tool=tools["reminder"],
        handoff_arguments=tool_arguments(tools["handoff"]),
        reminder_arguments=tool_arguments(tools["reminder"]),
        done_claims=(*folded(claims, "claims"), *folded(claims, "promises")),
        confirmations={
            "handed_off": canned_form(replies.handoff_confirmation),
            "requested": canned_form(replies.sentences["reminder_confirmation"]),
        },
    )
