import json
import shutil
from pathlib import Path

import pytest
from audit_support import BASELINE, Lab, new_lab
from guard_support import git

from gisting.eval.cli import main

REPO = Path(__file__).resolve().parents[2]
REPORT = "eval/reports/ee6c5c626278120523b9af02255958c0c9f5048c/full"


def real_baseline(**changes: float) -> str:
    document = json.loads((REPO / "eval" / "baseline.json").read_text(encoding="utf-8"))
    for item in document["epochs"]:
        if item["mode"] == "full":
            item["metrics"].update(changes)
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    lab = new_lab(tmp_path)
    lab.genesis({
        BASELINE: real_baseline(over_refusal_rate=0.5),
        "eval/metrics.toml": (REPO / "eval" / "metrics.toml").read_text(encoding="utf-8"),
    })
    git(lab.root, "rm", "-rq", "--", "eval/cases")
    for name in ("eval/cases", "data/demo-orders"):
        shutil.copytree(REPO / name, lab.root / name)
    shutil.copytree(REPO / "prompts", lab.root / "prompts", dirs_exist_ok=True)
    git(lab.root, "add", "--", "eval/cases", "data/demo-orders", "prompts")
    lab.commit({})
    return lab


def test_a_tightening_that_a_real_committed_report_holds_is_shown_as_such(
    tmp_path: Path, lab: Lab, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copytree(REPO / REPORT, lab.root / REPORT)
    git(lab.root, "add", "--", REPORT)
    lab.stage({BASELINE: real_baseline()})
    assert main(["guard-hash", "--root", str(lab.root), "--out", str(tmp_path / "m.msg")]) == 0
    out = capsys.readouterr().out
    assert f"baseline classification: Tighten (source report {REPORT})" in out
    assert "over_refusal_rate: 0.5 ->" in out
    assert "signature required: no" in out


def test_the_same_tightening_without_its_report_is_shown_as_needing_a_signature(
    tmp_path: Path, lab: Lab, capsys: pytest.CaptureFixture[str]
) -> None:
    lab.stage({BASELINE: real_baseline()})
    assert main(["guard-hash", "--root", str(lab.root), "--out", str(tmp_path / "m.msg")]) == 0
    out = capsys.readouterr().out
    assert "baseline classification: NeedsSignature" in out
    assert "no committed report" in out
    assert "signature required: yes" in out
