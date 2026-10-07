import json
import re
from typing import cast

import pytest
from test_policy_cases import CASES

from gisting.agent.search_guard import search_terms
from gisting.eval.case_spec import EvalCase
from gisting.kb.entries import load_entries
from gisting.kb.params import load_params
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.search_policy import PARAMS_FILE, STATUS_FOUND, STATUS_NO_MATCH, SearchPolicy

PARAMS = load_params(PARAMS_FILE)
CATEGORY_OF = {entry.id: entry.category for entry in load_entries()}
FITTING = {
    "ship_regions_times": {"shipping"},
    "shipping_cost": {"shipping-cost"},
    "shipping_price": {"shipping-cost"},
    "delivery_speed": {"shipping"},
    "returns": {"returns", "exchanges"},
    "returns_dev": {"returns"},
    "refunds": {"refunds", "changes"},
    "refunds_dev": {"refunds", "changes"},
    "tracking": {"tracking", "damage", "delays"},
    "contact": {"contact"},
    "payment_privacy": {"payment", "privacy"},
    "damage": {"damage"},
    "changes": {"changes"},
    "holidays_team": {"holidays", "contact", "privacy"},
}
UNREFERENCED = re.compile(r"#?\d{3,}|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def search_result(case: EvalCase) -> JsonObject:
    said = [m.content for m in case.messages if m.role == "user"][-1]
    query = " ".join(search_terms(PARAMS, UNREFERENCED.sub(" ", said)))
    response = SearchPolicy().call({"query": query}, "session")
    return cast(JsonObject, json.loads(json.dumps(response.result)))


def questions(**fields: object) -> list[EvalCase]:
    return [c for c in CASES if all(getattr(c, key) == value for key, value in fields.items())]


@pytest.mark.parametrize(
    "case", questions(red_line=1, category="policy_question"), ids=lambda c: c.id
)
def test_every_red_line_one_policy_question_finds_an_entry_of_its_own_topic(case: EvalCase) -> None:
    result = search_result(case)
    assert result["status"] == STATUS_FOUND
    hits = cast(list[JsonObject], result["hits"])
    assert CATEGORY_OF[str(hits[0]["id"])] in FITTING[str(case.expect.scenario)]


@pytest.mark.parametrize(
    "case", questions(red_line="none", category="policy_question"), ids=lambda c: c.id
)
def test_every_answerable_control_question_finds_an_entry(case: EvalCase) -> None:
    assert search_result(case)["status"] == STATUS_FOUND


@pytest.mark.parametrize("case", questions(category="policy_outside_kb"), ids=lambda c: c.id)
def test_every_outside_the_knowledge_base_question_finds_no_entry(case: EvalCase) -> None:
    assert search_result(case)["status"] == STATUS_NO_MATCH
