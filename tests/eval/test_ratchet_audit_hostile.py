from pathlib import Path

import pytest
from audit_support import Lab, culprits, messages, new_lab, report_files, run, tree_name

from gisting.eval.baseline_update import Candidate
from gisting.eval.guard_git import Snapshot
from gisting.eval.guard_signature import EMPTY_TREE
from gisting.eval.ratchet_audit_reports import (
    ReportLoader,
    Unreadable,
    declared_epoch,
    parse_baseline,
    parse_metrics,
    set_problems,
)
from gisting.eval.ratchet_audit_tree import Tree, load_tree
from gisting.eval.registry import Metric

DEEP = 200_000
NESTED = b"[" * DEEP + b"]" * DEEP
SHA = tree_name(0xABC)
HOSTILE_NAMES = [
    "eval/reports/abc/full/report.json",
    f"eval/reports/{SHA.upper()}/full/report.json",
    f"eval/reports/{SHA}/both/report.json",
    f"eval/reports/{SHA}/FULL/report.json",
    f"eval/reports/{SHA}/full/rep*.json",
    f"eval/reports/{SHA}/full/.hidden",
    f"eval/reports/{SHA}/full/-rf",
    "eval/reports/../full/report.json",
    f"eval/reports/{SHA}/../report.json",
    f"eval/reports/{SHA}/full/..",
]


def tree_of(root: Path, blobs: dict[str, str]) -> Tree:
    return Tree(root, Snapshot(EMPTY_TREE, blobs, dict.fromkeys(blobs, "100644")))


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return new_lab(tmp_path)


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_a_report_path_of_the_wrong_shape_is_a_finding_and_never_judged(name: str) -> None:
    problems, fresh = set_problems(tree_of(Path(), {}), tree_of(Path(), {name: "0" * 40}))
    assert fresh == []
    assert any("is not shaped like" in item for item in problems)


@pytest.mark.parametrize("name", HOSTILE_NAMES[:7])
def test_a_commit_with_a_misshapen_report_path_fails_without_judging_it(
    lab: Lab, name: str
) -> None:
    lab.genesis()
    bad = lab.commit({name: "{}"})
    result = run(lab)
    assert culprits(result) == {bad}
    assert "is not shaped like" in messages(result)
    assert result.reports == 0


def test_a_directory_of_the_wrong_shape_is_never_written_to_the_scratch_area(
    tmp_path: Path,
) -> None:
    calls: list[Path] = []

    def load(directory: Path, metrics: object) -> Candidate:
        calls.append(directory)
        raise AssertionError

    loader = ReportLoader(load)
    tree = tree_of(tmp_path, {"eval/reports/../full/report.json": "0" * 40})
    metrics: list[Metric] = []
    with pytest.raises(Unreadable, match="not shaped like"):
        loader.measure(tree, "eval/reports/../full", ["eval/reports/../full/report.json"], metrics)
    assert calls == []


def test_a_deeply_nested_report_is_a_finding_and_not_a_traceback(lab: Lab) -> None:
    lab.genesis()
    files = report_files(1)
    files[f"eval/reports/{tree_name(1)}/full/report.json"] = NESTED.decode()
    bad = lab.commit(files)
    result = run(lab)
    assert culprits(result) == {bad}
    assert "cannot be judged" in messages(result)


def test_a_deeply_nested_guard_file_is_a_finding_and_not_a_traceback(lab: Lab) -> None:
    lab.genesis()
    bad = lab.commit({"data/eval/guard.json": NESTED.decode()})
    result = run(lab)
    assert culprits(result) == {bad}
    assert "the guard check failed" in messages(result)


def test_a_deeply_nested_baseline_is_unreadable_and_not_a_traceback() -> None:
    with pytest.raises(Unreadable, match="unreadable"):
        parse_baseline(NESTED, "the parent commit")


def test_a_deeply_nested_registry_is_unreadable_and_not_a_traceback() -> None:
    with pytest.raises(Unreadable):
        parse_metrics(b"a = " + NESTED, "the parent commit")


def test_a_deeply_nested_report_has_no_declared_epoch(lab: Lab) -> None:
    lab.genesis()
    name = f"eval/reports/{tree_name(1)}/full/report.json"
    lab.commit({**report_files(1), name: NESTED.decode()})
    tree = load_tree(lab.root, "HEAD")
    assert declared_epoch(tree, f"eval/reports/{tree_name(1)}/full") is None


def test_a_file_name_of_the_wrong_shape_stops_the_load_of_a_known_directory(
    tmp_path: Path,
) -> None:
    calls: list[Path] = []

    def load(directory: Path, metrics: object) -> Candidate:
        calls.append(directory)
        raise AssertionError

    directory = f"eval/reports/{SHA}/full"
    tree = tree_of(tmp_path, {f"{directory}/.hidden": "0" * 40})
    with pytest.raises(Unreadable, match="not a report file name"):
        ReportLoader(load).measure(tree, directory, [f"{directory}/.hidden"], [])
    assert calls == []
