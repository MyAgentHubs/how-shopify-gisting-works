from pathlib import Path

import pytest

from gisting.eval.report import ReportError
from gisting.eval.report_identity import IdentityMismatch, identity_problems, require_identity
from gisting.shopify.jsonvalue import Json, JsonObject

TREE = "a" * 40
BACKEND = "backend-one"
DIRECTORY = Path("/repo/eval/reports") / TREE / "gist"


def internal(**changes: Json) -> JsonObject:
    base: JsonObject = {
        "mode": "gist",
        "backend_id": BACKEND,
        "gist_run_id": "run-1",
        "model": {"gist": {"run": "run-1"}},
    }
    return {**base, **changes}


def good_row(case_id: str) -> JsonObject:
    return {"case_id": case_id, "mode": "gist", "internal": internal()}


def good_report(**changes: Json) -> JsonObject:
    run: JsonObject = {"code_tree_sha": TREE, "mode": "gist", "backend_id": BACKEND}
    return {"run": {**run, **changes}}


def good_rows() -> list[JsonObject]:
    return [good_row("c1"), good_row("c2"), {"case_id": "c3", "mode": "gist", "error": {}}]


def fields(report: JsonObject, rows: list[JsonObject], directory: Path = DIRECTORY) -> list[str]:
    return [item.field for item in identity_problems(directory, report, rows)]


def test_a_consistent_report_has_no_problems() -> None:
    assert identity_problems(DIRECTORY, good_report(), good_rows()) == []
    require_identity(DIRECTORY, good_report(), good_rows())


def test_a_report_whose_mode_differs_from_its_directory_is_caught() -> None:
    assert set(fields(good_report(mode="full"), good_rows())) == {
        "mode",
        "gist_run_id",
        "model.gist",
    }


def test_a_report_in_the_directory_of_another_mode_is_caught() -> None:
    other = DIRECTORY.parent / "full"
    assert fields(good_report(), good_rows(), other) == ["mode"]


def test_a_report_whose_tree_differs_from_its_directory_is_caught() -> None:
    other = Path("/repo/eval/reports") / ("b" * 40) / "gist"
    assert fields(good_report(), good_rows(), other) == ["code_tree_sha"]


@pytest.mark.parametrize("backend", [None, "", "  ", 3])
def test_a_report_without_a_usable_backend_is_caught(backend: Json) -> None:
    assert fields(good_report(backend_id=backend), good_rows()) == ["backend_id"]


def test_a_report_without_a_run_section_is_caught() -> None:
    assert set(fields({}, good_rows())) >= {"code_tree_sha", "mode", "backend_id"}


def test_a_row_from_another_backend_is_caught_with_its_case() -> None:
    rows = good_rows()
    rows[1]["internal"] = internal(backend_id="backend-two")
    (problem,) = identity_problems(DIRECTORY, good_report(), rows)
    assert problem.field == "backend_id"
    assert "c2" in problem.where
    assert problem.found == "backend-two"


def test_a_row_from_another_mode_is_caught() -> None:
    rows = good_rows()
    rows[0]["internal"] = internal(mode="full")
    assert fields(good_report(), rows) == ["mode"]


def test_a_row_labelled_with_another_mode_at_the_top_is_caught() -> None:
    rows = good_rows()
    rows[0]["mode"] = "full"
    assert fields(good_report(), rows) == ["mode"]


def test_a_row_without_an_internal_trace_is_caught() -> None:
    rows = good_rows()
    del rows[0]["internal"]
    assert fields(good_report(), rows) == ["mode", "backend_id", "gist_run_id", "model.gist"]


def test_a_row_that_failed_to_run_carries_no_identity_and_is_skipped() -> None:
    rows: list[JsonObject] = [good_row("c1"), {"case_id": "c9", "error": {"type": "x"}}]
    assert identity_problems(DIRECTORY, good_report(), rows) == []


@pytest.mark.parametrize("rows", [[], [{"case_id": "c9", "error": {"type": "x"}}]])
def test_a_report_without_an_answered_row_is_caught(rows: list[JsonObject]) -> None:
    assert fields(good_report(), rows) == ["rows"]


def test_the_error_names_every_problem_up_to_a_few_and_counts_the_rest() -> None:
    rows: list[JsonObject] = [
        {**good_row(f"c{i}"), "internal": internal(backend_id="other")} for i in range(10)
    ]
    with pytest.raises(IdentityMismatch) as caught:
        require_identity(DIRECTORY, good_report(), rows)
    assert len(caught.value.problems) == 10
    assert "c0" in str(caught.value)
    assert "7 more" in str(caught.value)
    assert isinstance(caught.value, ReportError)


def row_with(**changes: Json) -> list[JsonObject]:
    return [{"case_id": "c1", "mode": "gist", "internal": internal(**changes)}]


@pytest.mark.parametrize("run_id", [None, "", "  ", 3])
def test_a_gist_row_without_a_usable_gist_run_id_is_caught(run_id: Json) -> None:
    assert fields(good_report(), row_with(gist_run_id=run_id)) == ["gist_run_id"]


@pytest.mark.parametrize("adapter", [None, {}, "run-1", ["run-1"]])
def test_a_gist_row_without_the_adapter_record_is_caught(adapter: Json) -> None:
    assert fields(good_report(), row_with(model={"gist": adapter})) == ["model.gist"]


def test_a_gist_row_without_a_model_record_is_caught() -> None:
    assert fields(good_report(), row_with(model=None)) == ["model.gist"]


FULL_DIRECTORY = DIRECTORY.parent / "full"


def full_rows(**changes: Json) -> list[JsonObject]:
    keys: JsonObject = {
        "mode": "full",
        "backend_id": BACKEND,
        "gist_run_id": None,
        "model": {"gist": None},
    }
    return [{"case_id": "c1", "internal": {**keys, **changes}}]


def test_a_full_row_that_carries_no_gist_is_consistent() -> None:
    report = good_report(mode="full")
    assert identity_problems(FULL_DIRECTORY, report, full_rows()) == []
    assert identity_problems(FULL_DIRECTORY, report, full_rows(model={})) == []


@pytest.mark.parametrize("empty", ["", {}, 0])
def test_a_full_row_with_an_empty_but_present_gist_field_is_caught(empty: Json) -> None:
    report = good_report(mode="full")
    assert fields(report, full_rows(gist_run_id=empty), FULL_DIRECTORY) == ["gist_run_id"]
    assert fields(report, full_rows(model={"gist": empty}), FULL_DIRECTORY) == ["model.gist"]


def test_a_full_row_with_a_gist_run_id_or_adapter_is_caught() -> None:
    report = good_report(mode="full")
    assert fields(report, full_rows(gist_run_id="run-1"), FULL_DIRECTORY) == ["gist_run_id"]
    adapter = full_rows(model={"gist": {"run": "r"}})
    assert fields(report, adapter, FULL_DIRECTORY) == ["model.gist"]
