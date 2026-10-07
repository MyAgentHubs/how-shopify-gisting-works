import io
import json
import sys
from pathlib import Path

import pytest

from gisting.kb.cli import main

REPO = Path(__file__).resolve().parents[2]


def feed(monkeypatch: pytest.MonkeyPatch, document: object) -> None:
    text = document if isinstance(document, str) else json.dumps(document)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def test_one_json_line_of_hits_on_stdout_and_nothing_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed(monkeypatch, {"query": "return window"})
    assert main(["search"]) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1
    hits = json.loads(captured.out)["hits"]
    assert hits[0]["id"] == "kb-return-window"
    assert set(hits[0]) == {
        "id",
        "score",
        "method",
        "category",
        "version",
        "title",
        "answer",
        "matched_terms",
    }
    assert hits[0]["method"] == "bm25"
    assert captured.err == ""


def test_top_k_defaults_from_data_and_is_capped_by_data(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed(monkeypatch, {"query": "shipping"})
    assert main(["search"]) == 0
    assert len(json.loads(capsys.readouterr().out)["hits"]) == 3
    feed(monkeypatch, {"query": "shipping", "top_k": 1})
    assert main(["search"]) == 0
    assert len(json.loads(capsys.readouterr().out)["hits"]) == 1
    feed(monkeypatch, {"query": "shipping", "top_k": 1000})
    assert main(["search"]) == 0
    assert len(json.loads(capsys.readouterr().out)["hits"]) == 10


def test_no_match_is_success_with_an_empty_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    feed(monkeypatch, {"query": "xyzzy"})
    assert main(["search"]) == 0
    assert json.loads(capsys.readouterr().out) == {"hits": []}


@pytest.mark.parametrize(
    "document",
    ["not json", "[]", {}, {"query": 3}, {"query": "a", "top_k": 0}, {"query": "a", "top_k": "2"}],
)
def test_invalid_input_exits_two_with_a_typed_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], document: object
) -> None:
    feed(monkeypatch, document)
    assert main(["search"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("gisting.kb: InvalidRequest:")


def test_corrupt_data_exits_one_with_a_typed_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    broken = tmp_path / "broken.jsonl"
    broken.write_text('{"id": "kb-x"}\n', encoding="utf-8")
    feed(monkeypatch, {"query": "a"})
    assert main(["search", "--entries", str(broken)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("gisting.kb: KbDataError:")


def test_missing_params_file_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    feed(monkeypatch, {"query": "a"})
    assert main(["search", "--params", str(tmp_path / "absent.json")]) == 1
    assert capsys.readouterr().err.startswith("gisting.kb: KbDataError:")
