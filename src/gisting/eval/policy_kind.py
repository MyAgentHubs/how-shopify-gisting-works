import json
from collections.abc import Mapping
from typing import cast

from gisting.eval.data_model import GraderData
from gisting.eval.text import canned_form
from gisting.prompt.parse import ParsedOutput
from gisting.prompt.schema import as_object

POLICY_ANSWER = "policy_answer"
POLICY_NO_MATCH = "policy_no_match"


def policy_documents(results: tuple[str, ...], data: GraderData) -> list[Mapping[str, object]]:
    found: list[Mapping[str, object]] = []
    for text in results:
        try:
            document = json.loads(text)
        except ValueError:
            continue
        fields = as_object(document)
        status = fields.get("status") if fields is not None else None
        if fields is not None and isinstance(status, str) and status in data.policy_statuses:
            found.append(fields)
    return found


def top_answer(document: Mapping[str, object]) -> str | None:
    node = document.get("hits")
    hits = cast(list[object], node) if isinstance(node, list) else []
    first = as_object(hits[0]) if hits else None
    answer = first.get("answer") if first is not None else None
    return answer if isinstance(answer, str) and answer.strip() else None


def searched_only(parsed: ParsedOutput, data: GraderData) -> bool:
    return bool(parsed.calls) and all(call.name == data.policy.tool for call in parsed.calls)


def policy_kind(parsed: ParsedOutput, results: tuple[str, ...], data: GraderData) -> str | None:
    if not parsed.content or (parsed.calls and not searched_only(parsed, data)):
        return None
    documents = policy_documents(results, data)
    if not documents:
        return None
    last, rules = documents[-1], data.policy
    if last.get("status") == rules.found_status:
        answer = top_answer(last)
        same = answer is not None and " ".join(parsed.content.split()) == " ".join(answer.split())
        return POLICY_ANSWER if same else None
    if last.get("status") == rules.no_match_status:
        return POLICY_NO_MATCH if canned_form(parsed.content) == rules.no_match_reply else None
    return None
