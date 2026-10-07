from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.facts import facts_json
from gisting.tools.outcomes import (
    Found,
    Locked,
    LookupOutcome,
    UpstreamError,
)

NO_MATCH = "no_match"
UNAVAILABLE = "unavailable"
LOCKED = "locked"


def render_result(outcome: LookupOutcome) -> JsonObject:
    if isinstance(outcome, Found):
        return {"status": "found", "order": facts_json(outcome.facts)}
    if isinstance(outcome, UpstreamError):
        return {"status": UNAVAILABLE}
    if isinstance(outcome, Locked):
        return {"status": LOCKED}
    return {"status": NO_MATCH}
