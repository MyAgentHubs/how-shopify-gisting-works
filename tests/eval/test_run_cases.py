import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fakes.agent_launch import inprocess_launcher

from gisting.eval.case_files import load_cases
from gisting.eval.runner import (
    Launched,
    RunFailed,
    RunSpec,
    Selection,
    run_cases,
    select_cases,
)
from gisting.shopify.demo_email import demo_email
from gisting.shopify.plan_transport import load_local_source

ROOT = Path(__file__).resolve().parents[2]
SECRET = "runner-test-secret-value"
LOADED, PROBLEMS = load_cases(ROOT)
ALL_EMAILS = [demo_email(SECRET, entry.order) for entry in load_local_source().plan.entries]


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / "empty.env"
    path.write_text("")
    return path


def read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_committed_cases_load_without_problems() -> None:
    assert PROBLEMS == []
    assert LOADED


def test_selection_filters_by_split_red_line_and_family() -> None:
    dev = select_cases(LOADED, Selection(("dev",)))
    assert dev
    assert {case.split for case in dev} == {"dev"}
    both = select_cases(LOADED, Selection(("dev", "train")))
    assert len(both) == len(LOADED)
    lines = select_cases(LOADED, Selection(("dev",), red_lines=("3", "none")))
    assert {str(case.red_line) for case in lines} == {"3", "none"}
    family = dev[0].family
    only = select_cases(LOADED, Selection(("dev",), families=(family,)))
    assert only
    assert {case.family for case in only} == {family}


def test_per_red_line_takes_the_first_few_of_each() -> None:
    chosen = select_cases(LOADED, Selection(("dev",), per_red_line=3))
    counts = {
        line: [str(c.red_line) for c in chosen].count(line) for line in ("1", "3", "4", "none")
    }
    assert counts == {"1": 3, "3": 3, "4": 3, "none": 3}


def test_a_small_run_writes_one_redacted_transcript_per_case(
    tmp_path: Path, env_file: Path
) -> None:
    cases = select_cases(LOADED, Selection(("dev",), per_red_line=3))
    result = run_cases(
        RunSpec(ROOT, "full", tmp_path, inprocess_launcher(env_file), env_file=env_file), cases
    )
    assert (result.cases, result.errors, result.unknown_emails) == (len(cases), 0, 0)
    text = result.path.read_text(encoding="utf-8")
    assert SECRET not in text
    assert not any(email in text for email in ALL_EMAILS)
    assert "@orders.example.com" not in text
    rows = read(result.path)
    assert [row["case_id"] for row in rows] == [case.id for case in cases]
    assert all(row["mode"] == "full" for row in rows)
    assert all(row["internal"]["backend_id"] == "fake-rule-model" for row in rows)
    assert all(row["headers"] == {} and row["cache_keys"] == [] for row in rows)


def test_the_filled_email_reaches_the_agent_and_comes_back_as_its_slot(
    tmp_path: Path, env_file: Path
) -> None:
    cases = select_cases(LOADED, Selection(("dev",), families=("dev_plain_lookup",)))[:2]
    result = run_cases(
        RunSpec(ROOT, "full", tmp_path, inprocess_launcher(env_file), env_file=env_file), cases
    )
    rows = read(result.path)
    first = rows[0]["internal"]["model_calls"][0]
    assert "{email_a}" in json.dumps(first["input_messages"])
    assert "{email_a}" in first["raw_output"]
    assert rows[0]["internal"]["tool_calls"][0]["trace"]["result_type"] == "Found"
    assert json.loads(rows[0]["internal"]["tool_calls"][0]["result"])["status"] == "found"


def test_gist_mode_is_passed_to_the_agent(tmp_path: Path, env_file: Path) -> None:
    cases = select_cases(LOADED, Selection(("dev",), per_red_line=1))
    result = run_cases(
        RunSpec(ROOT, "gist", tmp_path, inprocess_launcher(env_file), env_file=env_file), cases
    )
    rows = read(result.path)
    assert all(row["internal"]["mode"] == "gist" for row in rows)
    assert all(row["internal"]["gist_run_id"] == "run-x" for row in rows)


def test_a_missing_or_failed_row_becomes_an_error_transcript(
    tmp_path: Path, env_file: Path
) -> None:
    cases = select_cases(LOADED, Selection(("dev",), per_red_line=1))[:3]
    error = json.dumps({"error": {"type": "turn_error", "message": "boom"}})

    def launch(_argv: object, _stdin: str, _env: object) -> Launched:
        return Launched((error,), 1, "")

    result = run_cases(RunSpec(ROOT, "full", tmp_path, launch, env_file=env_file), cases)
    rows = read(result.path)
    assert result.errors == 3
    assert [row["error"]["type"] for row in rows] == ["turn_error", "missing_row", "missing_row"]


def test_an_agent_that_cannot_start_stops_the_run_without_echoing_an_email(
    tmp_path: Path, env_file: Path
) -> None:
    cases = select_cases(LOADED, Selection(("dev",), per_red_line=1))

    def launch(_argv: object, _stdin: str, _env: object) -> Launched:
        return Launched((), 2, f"gisting.agent: cannot load the model {ALL_EMAILS[0]}")

    with pytest.raises(RunFailed) as caught:
        run_cases(RunSpec(ROOT, "full", tmp_path, launch, env_file=env_file), cases)
    assert "cannot load the model" in str(caught.value)
    assert ALL_EMAILS[0] not in str(caught.value)
    assert not (tmp_path / "transcripts.jsonl").exists()


def test_more_result_lines_than_requests_is_a_failure(tmp_path: Path, env_file: Path) -> None:
    cases = select_cases(LOADED, Selection(("dev",), per_red_line=1))[:1]

    def launch(_argv: object, _stdin: str, _env: object) -> Launched:
        return Launched(("{}", "{}"), 0, "")

    with pytest.raises(RunFailed):
        run_cases(RunSpec(ROOT, "full", tmp_path, launch, env_file=env_file), cases)


def test_a_missing_secret_stops_the_run_before_the_agent_starts(
    tmp_path: Path, env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GISTING_EMAIL_SECRET")
    cases = select_cases(LOADED, Selection(("dev",), per_red_line=1))
    started: list[object] = []

    def launch(argv: object, _stdin: str, _env: object) -> Launched:
        started.append(argv)
        return Launched((), 0, "")

    with pytest.raises(RunFailed) as caught:
        run_cases(RunSpec(ROOT, "full", tmp_path, launch, env_file=env_file), cases)
    assert "GISTING_EMAIL_SECRET is not set" in str(caught.value)
    assert not started


def test_the_env_file_goes_to_the_email_lookup_and_to_the_agent(
    tmp_path: Path, env_file: Path
) -> None:
    cases = select_cases(LOADED, Selection(("dev",), per_red_line=1))[:1]
    seen: dict[str, list[str]] = {}

    def fetch(argv: Sequence[str], stdin: str, _env: object) -> Launched:
        seen["fetch"] = list(argv)
        orders = [json.loads(line)["order_number"] for line in stdin.splitlines()]
        rows = [json.dumps({"order_number": o, "email": demo_email(SECRET, o)}) for o in orders]
        return Launched(tuple(rows), 0, "")

    def launch(argv: Sequence[str], _stdin: str, _env: object) -> Launched:
        seen["agent"] = list(argv)
        return Launched((), 0, "")

    spec = RunSpec(ROOT, "full", tmp_path, launch, env_file=env_file, fetch=fetch)
    run_cases(spec, cases)
    for argv in seen.values():
        assert argv[-2:] == ["--env-file", str(env_file)]


def test_an_email_lookup_that_skips_an_order_is_a_failure(tmp_path: Path, env_file: Path) -> None:
    cases = select_cases(LOADED, Selection(("dev",), families=("dev_plain_lookup",)))[:1]

    def fetch(_argv: object, _stdin: str, _env: object) -> Launched:
        return Launched((), 0, "")

    spec = RunSpec(ROOT, "full", tmp_path, fetch=fetch, launch=fetch, env_file=env_file)
    with pytest.raises(RunFailed):
        run_cases(spec, cases)
