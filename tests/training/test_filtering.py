import json
from pathlib import Path

import pytest
from fakes.model import FakeModel
from fakes.tokenizer import synthetic_prompt_tokenizer
from training_support import EMAIL, first_sample

from gisting.eval.data import load_grader_data
from gisting.shopify.jsonvalue import required_object, required_str
from gisting.training.cli import main
from gisting.training.filtering import filter_rows, summary_json
from gisting.training.kit import make_kit
from gisting.training.samples import read_jsonl
from gisting.training.teacher import teach

DECLINE = "Sorry, I can only help with order and delivery questions at Gisting Lab Store."
CALL = (
    '<tool_call>\n{"name": "lookup_order", "arguments": '
    f'{{"order_number": "#1042", "email": "{EMAIL}"}}}}\n</tool_call>'
)


def teacher_file(tmp_path: Path, outputs: list[str]) -> Path:
    samples = [
        first_sample("offtopic", "poem one"),
        first_sample("offtopic", "poem two"),
        first_sample("order_full", f"Where is order #1042? {EMAIL}", "#1042"),
    ]
    path = tmp_path / "teacher.jsonl"
    teach(FakeModel(outputs), make_kit(synthetic_prompt_tokenizer(), 4), samples, path)
    return path


def test_only_rows_the_grader_passes_are_kept_and_regraded(tmp_path: Path) -> None:
    path = teacher_file(tmp_path, [DECLINE, "Roses are red.", CALL])
    filtered = filter_rows(read_jsonl(path), load_grader_data())
    kept_ids = [required_str(required_object(row, "sample"), "id") for row in filtered.kept_rows]
    assert kept_ids == [
        "s-offtopic-poem one",
        "s-order_full-Where is order #1042? ava.chen@example.com",
    ]
    assert [(r.sample_id, r.problems) for r in filtered.rejected] == [
        ("s-offtopic-poem two", ("not_a_refusal",))
    ]
    assert all(row["verdict"] == {"ok": True, "problems": []} for row in filtered.kept_rows)


def test_the_summary_counts_every_split_and_category_and_names_the_empty_ones(
    tmp_path: Path,
) -> None:
    path = teacher_file(tmp_path, ["Roses are red.", "Violets are blue.", CALL])
    summary = summary_json(filter_rows(read_jsonl(path), load_grader_data()))
    assert summary["kept"] == 1
    assert summary["rejected"] == 2
    assert summary["groups"] == [
        {"split": "dev", "category": "offtopic", "total": 2, "kept": 0},
        {"split": "dev", "category": "order_full", "total": 1, "kept": 1},
    ]
    assert summary["empty_groups"] == [{"split": "dev", "category": "offtopic"}]


def test_a_stale_stored_verdict_never_decides_which_rows_are_kept(tmp_path: Path) -> None:
    path = teacher_file(tmp_path, ["Roses are red.", DECLINE, CALL])
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["verdict"] = {"ok": True, "problems": []}
    rows[1]["verdict"] = {"ok": False, "problems": ["stale"]}
    filtered = filter_rows(rows, load_grader_data())
    assert [r.sample_id for r in filtered.rejected] == ["s-offtopic-poem one"]


def test_the_filter_command_writes_the_kept_rows_and_prints_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = teacher_file(tmp_path, [DECLINE, "Roses are red.", CALL])
    out = tmp_path / "nested" / "filtered.jsonl"
    capsys.readouterr()
    assert main(["filter", "--teacher", str(path), "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["kept"] == 2
    assert len(out.read_text().splitlines()) == 2
    assert captured.err == ""


def search_call(query: str) -> str:
    body = json.dumps({"name": "search_policy", "arguments": {"query": query}})
    return f"<tool_call>\n{body}\n</tool_call>"


@pytest.mark.parametrize("category", ["policy_question", "policy_outside_kb"])
def test_the_decision_layer_keeps_a_search_with_the_customers_own_words_and_drops_the_rest(
    tmp_path: Path, category: str
) -> None:
    text = "How long do refunds take to arrive?"
    samples = [first_sample(category, f"{text} {n}") for n in range(4)]
    outputs = [
        search_call("refunds take"),
        search_call("refund policy"),
        CALL,
        DECLINE,
    ]
    path = tmp_path / "teacher.jsonl"
    teach(FakeModel(outputs), make_kit(synthetic_prompt_tokenizer(), 4), samples, path)
    filtered = filter_rows(read_jsonl(path), load_grader_data(), "decision")
    kept = [required_str(required_object(r, "sample"), "id") for r in filtered.kept_rows]
    assert kept == [samples[0].id]
    assert [r.problems for r in filtered.rejected] == [
        ("query_term_not_said:policy,refund",),
        ("unexpected_arguments", "wrong_tool_name"),
        ("expected_exactly_one_tool_call",),
    ]
