import json
from collections.abc import Sequence

from gisting.agent.answers import LOOKUP
from gisting.agent.policy import InvalidCode
from gisting.prompt.parse import CallRequest
from gisting.tools.search_policy import TOOL_NAME as SEARCH

ALONE_CODES = {
    LOOKUP: InvalidCode.ONE_LOOKUP_AT_A_TIME,
    SEARCH: InvalidCode.ONE_SEARCH_AT_A_TIME,
}


def distinct_searches(calls: Sequence[CallRequest]) -> int:
    keys = {json.dumps(call.arguments, sort_keys=True, default=str) for call in calls}
    return len(keys)


def crowded_tools(calls: Sequence[CallRequest]) -> frozenset[str]:
    names = [call.name for call in calls]
    crowded: set[str] = set()
    if LOOKUP in names and len(calls) > 1:
        crowded.add(LOOKUP)
    searches = [call for call in calls if call.name == SEARCH]
    if searches and (len(searches) < len(calls) or distinct_searches(searches) > 1):
        crowded.add(SEARCH)
    return frozenset(crowded)
