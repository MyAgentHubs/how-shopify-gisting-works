import io
import json
import sys
from pathlib import Path

import pytest
from agent_support import EMAIL, SECRET, SESSION, demo_order, good_call
from fakes.model import FakeModel
from fakes.shopify import FakeTransport
from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.agent.cli import Runtime, main
from gisting.agent.identity import model_identity
from gisting.manifest.record import GistManifest
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.cli import Runtime as ToolsRuntime

GIST = GistManifest(
    "run-1", "rev1", "b" * 64, "c" * 64, "d" * 64, 16, 32, 700, "e" * 64, "f" * 64, "cpu", "a" * 64
)
IDENTITY: JsonObject = {"base_model_revision": "rev1", "base_model_sha256": "a" * 64}


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISTING_EMAIL_SECRET", SECRET)


def run_with(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    identity: JsonObject | None,
) -> dict[str, object]:
    request = {"session_id": SESSION, "messages": [{"role": "user", "content": f"#1042 {EMAIL}"}]}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    tools = ToolsRuntime(FakeTransport([demo_order()]), lambda _seconds: None)
    runtime = Runtime(tools, FakeModel([good_call()]), synthetic_prompt_tokenizer())
    if identity is not None:
        runtime = Runtime(tools, runtime.model, runtime.tokenizer, identity=identity)
    assert main(["run", "--internal", "--env-file", str(env_file)], runtime) == 0
    return json.loads(capsys.readouterr().out)


def test_the_internal_trace_names_the_model_that_answered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    document = run_with(monkeypatch, capsys, tmp_path, IDENTITY)
    internal = document["internal"]
    assert isinstance(internal, dict)
    assert internal["model"] == IDENTITY
    assert "model" not in json.dumps(document["trace"])


def test_an_unnamed_model_leaves_an_empty_identity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    internal = run_with(monkeypatch, capsys, tmp_path, None)["internal"]
    assert isinstance(internal, dict)
    assert internal["model"] == {}


def test_identity_reads_the_revision_and_the_checksum_file_hash(tmp_path: Path) -> None:
    (tmp_path / ".revision").write_text("abc123\n")
    (tmp_path / "SHA256SUMS").write_text("0" * 64 + "  model.safetensors\n")
    found = model_identity(tmp_path, None)
    assert found["base_model_revision"] == "abc123"
    assert isinstance(found["base_model_sha256"], str)
    assert "gist" not in found


def test_a_model_dir_without_the_revision_files_gives_an_empty_identity(tmp_path: Path) -> None:
    assert model_identity(tmp_path, None) == {}


def test_a_gist_adds_its_run_and_hashes_but_no_vectors(tmp_path: Path) -> None:
    found = model_identity(tmp_path, GIST)
    gist = found["gist"]
    assert isinstance(gist, dict)
    assert gist["run_id"] == "run-1"
    assert gist["k"] == 16
    assert {"gist_sha256", "dataset_sha256", "train_config_sha256", "rules_sha256"} <= set(gist)
