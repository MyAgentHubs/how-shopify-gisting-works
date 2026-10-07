import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from baseline_support import (
    BAD,
    GOOD,
    ONE_BAD,
    baseline,
    changed,
    commit_baseline,
    make_root,
    make_run,
    refused_with,
    rewrite_rows,
    update,
)

from gisting.eval.cli_baseline import load_candidate
from gisting.eval.registry import load_registry
from gisting.eval.runner import Selection

FAMILIES = ("arrival_day_no_order", "delivered_status_ask")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return make_root(tmp_path, monkeypatch)


def test_the_first_run_of_an_epoch_is_recorded_as_it_is(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_run(root, GOOD)
    assert update(root, "--after", str(good)) == 0
    (item,) = baseline(root)["epochs"]
    assert (item["backend_id"], len(item["rules_version"])) == ("fake-rule-model", 16)
    assert item["metrics"]["fact_provenance_failures"] == 0.0
    assert item["metrics"]["prefill_tokens_per_turn"] > 0
    assert "fact_provenance_failures: new" in capsys.readouterr().out
    assert changed(root) == "M eval/baseline.json"


def test_a_significant_paired_improvement_tightens_the_baseline(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad, good = make_run(root, BAD, spoil=8), make_run(root, GOOD)
    assert update(root, "--after", str(bad)) == 0
    assert baseline(root)["epochs"][0]["metrics"]["fact_provenance_failures"] == 1.0
    commit_baseline(root)
    capsys.readouterr()
    assert update(root, "--after", str(good), "--before", str(bad)) == 0
    assert baseline(root)["epochs"][0]["metrics"]["fact_provenance_failures"] == 0.0
    assert "tightened 1.0 -> 0.0 8 cases fixed, 0 broken, p=0.00781" in capsys.readouterr().out
    assert changed(root) == "M eval/baseline.json"


def test_one_fixed_case_is_not_enough_to_tighten(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    one, good = make_run(root, ONE_BAD, spoil=1), make_run(root, GOOD)
    assert update(root, "--after", str(one)) == 0
    commit_baseline(root)
    capsys.readouterr()
    assert update(root, "--after", str(good), "--before", str(one)) == 0
    assert baseline(root)["epochs"][0]["metrics"]["fact_provenance_failures"] == 0.125
    assert "improvement not significant" in capsys.readouterr().out


def test_an_improvement_without_the_earlier_run_is_refused(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad, good = make_run(root, BAD, spoil=8), make_run(root, GOOD)
    assert update(root, "--after", str(bad)) == 0
    commit_baseline(root)
    before = (root / "eval" / "baseline.json").read_text(encoding="utf-8")
    assert update(root, "--after", str(good)) == 2
    assert "--before" in capsys.readouterr().err
    assert (root / "eval" / "baseline.json").read_text(encoding="utf-8") == before


def test_a_worse_run_is_refused_and_the_file_is_untouched(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad, good = make_run(root, BAD, spoil=8), make_run(root, GOOD)
    assert update(root, "--after", str(good)) == 0
    commit_baseline(root)
    before = (root / "eval" / "baseline.json").read_text(encoding="utf-8")
    assert update(root, "--after", str(bad), "--before", str(good)) == 2
    assert "signature" in capsys.readouterr().err
    assert (root / "eval" / "baseline.json").read_text(encoding="utf-8") == before


def test_other_uncommitted_changes_are_refused(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_run(root, GOOD)
    (root / "prompts" / "extra.txt").write_text("x")
    assert update(root, "--after", str(good)) == 2
    assert "on its own" in capsys.readouterr().err
    assert baseline(root)["epochs"] == []


def test_a_report_that_no_longer_matches_its_transcripts_is_refused(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_run(root, GOOD)
    with (good / "transcripts.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    assert update(root, "--after", str(good)) == 2
    assert "does not belong" in capsys.readouterr().err


def test_a_report_without_a_mode_is_refused(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = make_run(root, GOOD)
    path = good / "report.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    del document["run"]["mode"]
    path.write_text(json.dumps(document), encoding="utf-8")
    assert update(root, "--after", str(good)) == 2
    assert "mode" in capsys.readouterr().err
    assert baseline(root)["epochs"] == []


def test_a_recorded_epoch_carries_the_mode_of_the_run(root: Path) -> None:
    assert update(root, "--after", str(make_run(root, GOOD))) == 0
    (item,) = baseline(root)["epochs"]
    assert item["mode"] == "full"


def epoch_of(root: Path, mode: str) -> dict[str, Any]:
    (item,) = [item for item in baseline(root)["epochs"] if item["mode"] == mode]
    return item


def test_a_worse_gist_run_is_refused_even_when_the_full_epoch_is_as_bad(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    full_bad, gist_good = make_run(root, BAD, spoil=8), make_run(root, GOOD, mode="gist")
    gist_bad = make_run(root, BAD, spoil=8, mode="gist")
    assert update(root, "--after", str(full_bad)) == 0
    commit_baseline(root)
    assert update(root, "--after", str(gist_good)) == 0
    commit_baseline(root)
    before = (root / "eval" / "baseline.json").read_text(encoding="utf-8")
    assert epoch_of(root, "gist")["metrics"]["fact_provenance_failures"] == 0.0
    assert update(root, "--after", str(gist_bad), "--before", str(gist_good)) == 2
    assert "signature" in capsys.readouterr().err
    assert (root / "eval" / "baseline.json").read_text(encoding="utf-8") == before


def test_a_gist_improvement_tightens_the_gist_epoch_and_leaves_the_full_epoch_alone(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    full_good, gist_bad = make_run(root, GOOD), make_run(root, BAD, spoil=8, mode="gist")
    gist_good = make_run(root, GOOD, mode="gist")
    assert update(root, "--after", str(full_good)) == 0
    commit_baseline(root)
    assert update(root, "--after", str(gist_bad)) == 0
    commit_baseline(root)
    full_before = epoch_of(root, "full")
    capsys.readouterr()
    assert update(root, "--after", str(gist_good), "--before", str(gist_bad)) == 0
    assert "tightened 1.0 -> 0.0 8 cases fixed, 0 broken" in capsys.readouterr().out
    assert epoch_of(root, "gist")["metrics"]["fact_provenance_failures"] == 0.0
    assert epoch_of(root, "full") == full_before
    assert len(baseline(root)["epochs"]) == 2


def test_a_report_with_an_unknown_mode_is_refused(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_run(root, GOOD)
    path = good / "report.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    for mode in ("Gist", "FULL", "both", "", " gist", None, 1, ["gist"]):
        document["run"]["mode"] = mode
        path.write_text(json.dumps(document), encoding="utf-8")
        assert update(root, "--after", str(good)) == 2, mode
        assert "mode" in capsys.readouterr().err, mode
    assert baseline(root)["epochs"] == []


def test_a_row_from_another_backend_is_refused(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_run(root, GOOD)
    rewrite_rows(good, lambda rows: rows[3]["internal"].update(backend_id="other-backend"))
    refused_with(root, capsys, good, "backend_id")


def test_a_row_from_another_mode_is_refused(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = make_run(root, GOOD)
    rewrite_rows(good, lambda rows: rows[0]["internal"].update(mode="gist"))
    refused_with(root, capsys, good, "mode")


def test_a_report_that_names_another_backend_than_its_rows_is_refused(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_run(root, GOOD)
    path = good / "report.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["run"]["backend_id"] = "other-backend"
    path.write_text(json.dumps(document), encoding="utf-8")
    refused_with(root, capsys, good, "backend_id")


def test_a_report_kept_in_the_directory_of_another_mode_is_refused(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_run(root, GOOD)
    moved = root / "eval" / "reports" / GOOD / "gist"
    shutil.copytree(good, moved)
    refused_with(root, capsys, moved, "mode")


def test_a_report_kept_under_the_tree_of_another_run_is_refused(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = make_run(root, GOOD)
    moved = root / "eval" / "reports" / BAD / "full"
    shutil.copytree(good, moved)
    refused_with(root, capsys, moved, "code_tree_sha")


def test_a_candidate_keeps_the_dev_cases_for_ratchets_and_every_case_for_red_lines(
    root: Path,
) -> None:
    both = make_run(root, GOOD, selection=Selection(("dev", "train"), families=FAMILIES))
    metrics, _problems = load_registry(root / "eval" / "metrics.toml")
    candidate = load_candidate(both, root, metrics)
    name = "fact_provenance_failures"
    assert 0 < len(candidate.failed[name]) < len(candidate.whole[name])
    assert set(candidate.failed[name]) <= set(candidate.whole[name])
