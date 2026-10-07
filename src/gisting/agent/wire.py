import json

from gisting.agent.state import TurnResult
from gisting.prompt.messages import AssistantMessage, Message, UserMessage
from gisting.shopify.demo_apply import UsageError
from gisting.shopify.jsonvalue import Json


def parse_message(item: Json) -> Message:
    if not isinstance(item, dict) or not isinstance(item.get("content"), str):
        message = 'each message needs a "role" and a string "content"'
        raise UsageError(message)
    content = str(item["content"])
    if item.get("role") == "user":
        return UserMessage(content)
    if item.get("role") == "assistant":
        return AssistantMessage(content)
    message = 'message role must be "user" or "assistant"'
    raise UsageError(message)


def parse_request(document: Json) -> tuple[str, list[Message]]:
    if not isinstance(document, dict):
        message = "stdin must be a JSON object"
        raise UsageError(message)
    session_id, raw = document.get("session_id"), document.get("messages")
    if not isinstance(session_id, str) or not session_id or not isinstance(raw, list) or not raw:
        message = 'stdin needs a non-empty "session_id" string and a non-empty "messages" list'
        raise UsageError(message)
    messages = [parse_message(item) for item in raw]
    if not isinstance(messages[-1], UserMessage):
        message = "the last message must be from the user"
        raise UsageError(message)
    return session_id, messages


def wire(result: TurnResult, *, internal: bool) -> str:
    document: dict[str, object] = {"answer": result.answer, "trace": result.traces.public}
    if internal:
        document["internal"] = result.traces.internal
    return json.dumps(document, sort_keys=True)
