from pathlib import Path

import pytest
from fakes.tokenizer import synthetic_prompt_tokenizer

torch = pytest.importorskip("torch", reason="torch is in the model extra and absent in CI")
transformers = pytest.importorskip("transformers", reason="transformers is in the model extra")

from fakes.tiny_qwen import HIDDEN, K, make_model_dir, random_gist  # noqa: E402

from gisting.manifest.record import GistManifest, sha256_file, write_manifest  # noqa: E402
from gisting.model_server.gist import GistInjection  # noqa: E402
from gisting.model_server.gist_store import expected_for, write_gist  # noqa: E402
from gisting.prompt.assemble import assemble, gist_rules, tools_segment  # noqa: E402
from gisting.prompt.messages import UserMessage  # noqa: E402
from gisting.prompt.schema import load_tool_schemas  # noqa: E402
from gisting.prompt.tokenizer import PromptTokenizer  # noqa: E402


def gist_prompt(tokenizer: PromptTokenizer, text: str = "Where is order #1042?") -> list[int]:
    tools = tools_segment(tokenizer, load_tool_schemas().values())
    return assemble(tokenizer, gist_rules(tokenizer, K), tools, [UserMessage(text)]).ids


def make_artifact(
    directory: Path, model_dir: Path, gist: GistInjection, backend_id: str
) -> GistManifest:
    tokenizer = synthetic_prompt_tokenizer()
    expected = expected_for(model_dir, tokenizer, HIDDEN, backend_id)
    path = write_gist(directory, gist.vectors)
    manifest = GistManifest(
        run_id="run-test",
        base_model_revision=expected.base_model_revision,
        base_model_sha256=expected.base_model_sha256,
        rules_sha256=expected.rules_sha256,
        tools_sha256=expected.tools_sha256,
        k=gist.count,
        hidden_size=HIDDEN,
        placeholder_id=expected.placeholder_id,
        train_config_sha256="1" * 64,
        dataset_sha256="2" * 64,
        backend_id=backend_id,
        gist_sha256=sha256_file(path),
    )
    write_manifest(directory, manifest)
    return manifest


CPU_BACKEND = "transformers-cpu-float32"


def setup_artifact(
    tmp_path: Path, backend_id: str = CPU_BACKEND, seed: int = 1
) -> tuple[Path, Path, GistManifest]:
    model_dir = make_model_dir(tmp_path / "model")
    directory = tmp_path / "gist"
    directory.mkdir()
    gist = random_gist(synthetic_prompt_tokenizer(), seed)
    return directory, model_dir, make_artifact(directory, model_dir, gist, backend_id)
