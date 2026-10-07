import json

from conftest import SCRIPTS_DIR, Guard, Populate

REPO = SCRIPTS_DIR.parent
SCRIPT = "check_eval_registry.py"
METRICS = "eval/metrics.toml"
BASELINE = "eval/baseline.json"
GOOD_METRICS = (REPO / METRICS).read_text(encoding="utf-8")
EMPTY_BASELINE = json.dumps({"version": 1, "epochs": []})


def test_the_committed_registry_and_baseline_pass(guard: Guard) -> None:
    result = guard(SCRIPT, REPO)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_a_gated_metric_missing_a_field_fails(populate: Populate, guard: Guard) -> None:
    broken = GOOD_METRICS.replace("where_to_look", "where_to_loook", 1)
    result = guard(SCRIPT, populate({METRICS: broken, BASELINE: EMPTY_BASELINE}))
    assert result.returncode == 1
    assert "where_to_look is required for a gated metric" in result.stderr


def test_a_baseline_naming_an_unregistered_metric_fails(populate: Populate, guard: Guard) -> None:
    stray = json.dumps({
        "version": 1,
        "epochs": [
            {"backend_id": "b", "rules_version": "r", "mode": "full", "metrics": {"stray": 1}}
        ],
    })
    result = guard(SCRIPT, populate({METRICS: GOOD_METRICS, BASELINE: stray}))
    assert result.returncode == 1
    assert "unregistered metric stray" in result.stderr


def test_a_baseline_with_registered_null_values_passes(populate: Populate, guard: Guard) -> None:
    empty = json.dumps({
        "version": 1,
        "epochs": [
            {
                "backend_id": "b",
                "rules_version": "r",
                "mode": "full",
                "metrics": {"over_refusal_rate": None},
            }
        ],
    })
    result = guard(SCRIPT, populate({METRICS: GOOD_METRICS, BASELINE: empty}))
    assert (result.returncode, result.stderr) == (0, "")


def test_a_malformed_baseline_fails(populate: Populate, guard: Guard) -> None:
    result = guard(SCRIPT, populate({METRICS: GOOD_METRICS, BASELINE: '{"version": 2}'}))
    assert result.returncode == 1
    assert BASELINE in result.stderr


def test_missing_files_fail(populate: Populate, guard: Guard) -> None:
    result = guard(SCRIPT, populate({"README": "x"}))
    assert result.returncode == 1
    assert METRICS in result.stderr
    assert BASELINE in result.stderr
