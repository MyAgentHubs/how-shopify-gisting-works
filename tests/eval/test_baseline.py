import json
from pathlib import Path

import pytest

from gisting.eval.baseline import (
    Baseline,
    EpochMismatch,
    baseline_problems,
    load_baseline,
    metric_delta,
    parse_mode,
)
from gisting.eval.cli_baseline import load_candidate
from gisting.eval.dataclass_json import DecodeError
from gisting.eval.registry import load_registry
from gisting.eval.runner import MODES as RUN_MODES
from gisting.eval.web_benchmarks import MODES as WEB_MODES

REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / "eval" / "baseline.json"


def epoch(
    backend: str, rules: str, mode: str = "full", **metrics: float | None
) -> dict[str, object]:
    return {"backend_id": backend, "rules_version": rules, "mode": mode, "metrics": metrics}


def baseline_of(*epochs: dict[str, object]) -> Baseline:
    return Baseline.parse({"version": 1, "epochs": list(epochs)})


def committed_dev_values(backend: str, rules: str, mode: str) -> list[dict[str, float | None]]:
    metrics, _ = load_registry(REPO / "eval" / "metrics.toml")
    values: list[dict[str, float | None]] = []
    for path in sorted((REPO / "eval" / "reports").glob("*/*/report.json")):
        run = json.loads(path.read_text(encoding="utf-8"))["run"]
        if (run["backend_id"], run["rules_version"], run["mode"]) == (backend, rules, mode):
            values.append(load_candidate(path.parent, REPO, metrics).values)
    return values


def test_every_committed_baseline_value_comes_from_a_committed_report() -> None:
    baseline = load_baseline(BASELINE)
    for item in baseline.epochs:
        candidates = committed_dev_values(item.backend_id, item.rules_version, item.mode)
        assert candidates, item.key
        for name, value in item.metrics.items():
            assert any(found.get(name) == value for found in candidates), (item.key, name)


def test_epochs_are_found_by_backend_and_rules_version() -> None:
    baseline = baseline_of(epoch("cpu-a", "r1", m=3), epoch("cpu-a", "r2", m=4))
    found = baseline.epoch("cpu-a", "r2", "full")
    assert found is not None
    assert found.metrics == {"m": 4.0}
    assert baseline.epoch("gpu-b", "r1", "full") is None


def test_full_and_gist_epochs_of_one_backend_and_rules_are_separate() -> None:
    baseline = baseline_of(epoch("cpu-a", "r1", "full", m=3), epoch("cpu-a", "r1", "gist", m=7))
    full, gist = baseline.epoch("cpu-a", "r1", "full"), baseline.epoch("cpu-a", "r1", "gist")
    assert full is not None
    assert gist is not None
    assert (full.metrics, gist.metrics) == ({"m": 3.0}, {"m": 7.0})
    with pytest.raises(EpochMismatch):
        metric_delta(full, gist, "m")


def test_an_epoch_without_a_mode_is_rejected() -> None:
    old_format: dict[str, object] = {"backend_id": "cpu-a", "rules_version": "r1", "metrics": {}}
    with pytest.raises(DecodeError):
        Baseline.parse({"version": 1, "epochs": [old_format]})
    with pytest.raises(DecodeError):
        baseline_of(epoch("cpu-a", "r1", "both"))


@pytest.mark.parametrize("mode", ["Gist", "FULL", "both", "", " gist", None, 1, True, ["gist"]])
def test_only_full_and_gist_are_modes(mode: object) -> None:
    assert parse_mode(mode) is None
    with pytest.raises(DecodeError):
        baseline_of(epoch("cpu-a", "r1", mode=str(mode)))
    assert (parse_mode("full"), parse_mode("gist")) == ("full", "gist")


def test_every_mode_list_is_derived_from_the_baseline_mode_type() -> None:
    assert RUN_MODES == WEB_MODES == ("full", "gist")


def test_null_values_are_allowed_and_mean_not_measured() -> None:
    found = baseline_of(epoch("cpu-a", "r1", m=None)).epoch("cpu-a", "r1", "full")
    assert found is not None
    assert found.metrics == {"m": None}


def test_the_same_epoch_can_be_compared() -> None:
    baseline = baseline_of(epoch("cpu-a", "r1", m=3), epoch("cpu-a", "r1x", m=5))
    old = baseline.epoch("cpu-a", "r1", "full")
    assert old is not None
    assert metric_delta(old, old, "m") == 0.0


def test_different_rules_versions_are_never_compared() -> None:
    baseline = baseline_of(epoch("cpu-a", "r1", m=3), epoch("cpu-a", "r2", m=4))
    old, new = baseline.epoch("cpu-a", "r1", "full"), baseline.epoch("cpu-a", "r2", "full")
    assert old is not None
    assert new is not None
    with pytest.raises(EpochMismatch):
        metric_delta(old, new, "m")


def test_different_backends_are_never_compared() -> None:
    baseline = baseline_of(epoch("cpu-a", "r1", m=3), epoch("gpu-b", "r1", m=3))
    old, new = baseline.epoch("cpu-a", "r1", "full"), baseline.epoch("gpu-b", "r1", "full")
    assert old is not None
    assert new is not None
    with pytest.raises(EpochMismatch):
        metric_delta(old, new, "m")


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_values_are_rejected_when_the_file_is_loaded(tmp_path: Path, bad: str) -> None:
    text = (
        '{"version": 1, "epochs": [{"backend_id": "b", "rules_version": "r",'
        f' "mode": "full", "metrics": {{"m": {bad}}}}}]}}'
    )
    path = tmp_path / "baseline.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(DecodeError, match="finite"):
        load_baseline(path)


@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), float("-inf"), pytest.param(10**400, id="huge-int")]
)
def test_non_finite_values_are_rejected_when_parsed(bad: float) -> None:
    with pytest.raises(DecodeError, match="finite"):
        baseline_of(epoch("cpu-a", "r1", m=bad))


def test_a_missing_value_gives_no_delta() -> None:
    baseline = baseline_of(epoch("cpu-a", "r1", m=None))
    found = baseline.epoch("cpu-a", "r1", "full")
    assert found is not None
    assert metric_delta(found, found, "m") is None
    assert metric_delta(found, found, "absent") is None


def test_duplicate_epochs_are_rejected() -> None:
    with pytest.raises(DecodeError, match="duplicate"):
        baseline_of(epoch("cpu-a", "r1"), epoch("cpu-a", "r1"))


def test_structural_errors_are_rejected() -> None:
    with pytest.raises(DecodeError):
        Baseline.parse({"version": 2, "epochs": []})
    with pytest.raises(DecodeError):
        Baseline.parse({
            "version": 1,
            "epochs": [{"backend_id": "", "rules_version": "r", "mode": "full"}],
        })
    with pytest.raises(DecodeError):
        baseline_of(epoch("cpu-a", "r1", m="3"))  # pyright: ignore[reportArgumentType]


def test_baseline_metrics_must_be_registered() -> None:
    baseline = baseline_of(epoch("cpu-a", "r1", known=1, stray=2))
    assert baseline_problems(baseline, frozenset({"known"})) == [
        "epoch cpu-a/r1/full has unregistered metric stray"
    ]


def test_a_malformed_file_raises_a_decode_error(tmp_path: Path) -> None:
    broken = tmp_path / "baseline.json"
    broken.write_text(json.dumps([1]), encoding="utf-8")
    with pytest.raises(DecodeError):
        load_baseline(broken)
