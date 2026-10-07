import json
from pathlib import Path

from fakes.model import FakeModel
from fakes.tokenizer import synthetic_prompt_tokenizer
from training_support import EMAIL, first_sample, second_sample

from gisting.prompt.tokenizer import IM_END
from gisting.training.kit import make_kit
from gisting.training.samples import sample_json
from gisting.training.teacher import read_teacher, teach

ARGUMENTS = {"order_number": "#1042", "email": EMAIL}
CALL = (
    "<tool_call>\n"
    + json.dumps({"name": "lookup_order", "arguments": ARGUMENTS})
    + "\n</tool_call>"
)


def test_teacher_cache_keeps_wrong_answers_and_marks_them(tmp_path: Path) -> None:
    kit = make_kit(synthetic_prompt_tokenizer(), 4)
    model = FakeModel([CALL, "It is on its way."])
    right = first_sample("order_full", f"Where is order #1042? {EMAIL}", "#1042")
    wrong = first_sample("order_full", f"Where is order #1042 now? {EMAIL}", "#1042")
    out = tmp_path / "teacher.jsonl"
    assert teach(model, kit, [right, wrong], out) == 2
    records = read_teacher(out)
    assert [record.verdict.ok for record in records] == [True, False]
    assert records[1].verdict.problems == ("expected_exactly_one_tool_call",)
    assert records[1].text == "It is on its way."


def test_teacher_prompt_uses_the_full_rules_and_the_sample_messages(tmp_path: Path) -> None:
    tokenizer = synthetic_prompt_tokenizer()
    kit = make_kit(tokenizer, 4)
    model = FakeModel(["ok"])
    sample = second_sample()
    teach(model, kit, [sample], tmp_path / "t.jsonl")
    assert model.prompts[0] == kit.prompt(sample.messages, gist=False).ids
    assert tokenizer.gist_placeholder not in model.prompts[0]
    assert model.limits == [kit.max_new_tokens]


def test_teach_resumes_without_repeating_finished_samples(tmp_path: Path) -> None:
    kit = make_kit(synthetic_prompt_tokenizer(), 4)
    out = tmp_path / "t.jsonl"
    sample = first_sample("offtopic", "write a poem")
    assert teach(FakeModel(["Sorry, orders only."]), kit, [sample], out) == 1
    assert teach(FakeModel([]), kit, [sample], out) == 0
    assert len(out.read_text().splitlines()) == 1


def test_target_ids_end_with_the_stop_token_only_when_the_teacher_stopped(tmp_path: Path) -> None:
    tokenizer = synthetic_prompt_tokenizer()
    kit = make_kit(tokenizer, 4)
    out = tmp_path / "t.jsonl"
    teach(FakeModel(["a"]), kit, [first_sample("offtopic", "poem")], out)
    record = read_teacher(out)[0]
    assert record.target_ids(kit) == [*record.ids, tokenizer.control(IM_END)]
    row = json.loads(out.read_text())
    row["teacher"]["finish_reason"] = "length"
    out.write_text(json.dumps(row) + "\n")
    assert read_teacher(out)[0].target_ids(kit) == list(record.ids)


def test_records_embed_the_sample_the_backend_and_the_token_composition(tmp_path: Path) -> None:
    kit = make_kit(synthetic_prompt_tokenizer(), 4)
    out = tmp_path / "t.jsonl"
    sample = first_sample("offtopic", "poem")
    teach(FakeModel(["no"]), kit, [sample], out)
    row = json.loads(out.read_text())
    assert row["sample"] == json.loads(json.dumps(sample_json(sample)))
    assert row["teacher"]["backend_id"] == "fake-model"
    assert row["teacher"]["prompt_tokens"]["rules"] > 0
