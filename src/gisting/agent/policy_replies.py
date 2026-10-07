from gisting.agent.answers import AnswerRules
from gisting.prompt.phrases import ReplyPhrases
from gisting.prompt.replies import Unrenderable
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.search_policy import (
    STATUS_FOUND,
    STATUS_NO_MATCH,
    STATUS_UNAVAILABLE,
    TOOL_NAME,
)

NO_MATCH_PHRASE = "policy_no_match"
POLICY_UNAVAILABLE = "policy_unavailable"


class MissingPhrase(ValueError):
    pass


def no_match_reply(phrases: ReplyPhrases) -> str | None:
    phrase = phrases.sentences.get(NO_MATCH_PHRASE)
    return None if phrase is None else f"{phrase} {phrases.handoff_offer}"


def top_answer(result: JsonObject) -> str | None:
    hits = result.get("hits")
    first = hits[0] if isinstance(hits, list) and hits else None
    answer = first.get("answer") if isinstance(first, dict) else None
    return answer if isinstance(answer, str) and answer.strip() else None


def policy_reply(rules: AnswerRules, tool: str, result: JsonObject) -> str | Unrenderable | None:
    if tool != TOOL_NAME:
        return None
    status = result.get("status")
    if status == STATUS_FOUND:
        return top_answer(result) or Unrenderable(f"{STATUS_FOUND}:no_answer")
    if status == STATUS_NO_MATCH:
        reply = no_match_reply(rules.phrases)
        if reply is None:
            message = f"reply_phrases.json has no sentence named {NO_MATCH_PHRASE}"
            raise MissingPhrase(message)
        return reply
    reason = STATUS_UNAVAILABLE if status == STATUS_UNAVAILABLE else f"result_status:{status}"
    return Unrenderable(reason)
