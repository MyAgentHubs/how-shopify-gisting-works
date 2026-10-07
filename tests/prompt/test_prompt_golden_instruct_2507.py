import pytest
from fakes.real_model import MODEL_DIR
from prompt_support import FOUND, LOOKUP, build, hf_messages
from test_prompt_golden import CONVERSATIONS

from gisting.prompt.messages import ToolMessage
from gisting.prompt.schema import load_tool_schemas
from gisting.prompt.tokenizer import PromptTokenizer

THINKING_BLOCK_TOKENS = 4
INSTRUCT_DIR = MODEL_DIR.parent / "qwen3-4b-instruct-2507"
needs_instruct = pytest.mark.skipif(
    not (INSTRUCT_DIR / "tokenizer.json").is_file(),
    reason=f"no tokenizer.json in {INSTRUCT_DIR}; CI has no model files, run locally with them",
)


@needs_instruct
@pytest.mark.parametrize("name", list(CONVERSATIONS))
def test_ids_equal_the_instruct_2507_reference_chat_template(name: str) -> None:
    transformers = pytest.importorskip("transformers", reason="transformers is in the model extra")
    reference = transformers.AutoTokenizer.from_pretrained(str(INSTRUCT_DIR))
    messages = CONVERSATIONS[name]
    expected = reference.apply_chat_template(
        hf_messages(messages),
        tools=[schema.function_json() for schema in load_tool_schemas().values()],
        add_generation_prompt=True,
        tokenize=True,
        return_dict=False,
    )
    assert build(PromptTokenizer.from_dir(INSTRUCT_DIR), messages).ids == list(expected)


@needs_instruct
def test_instruct_2507_conversation_ends_at_the_assistant_header() -> None:
    tokenizer = PromptTokenizer.from_dir(INSTRUCT_DIR)
    ids = build(tokenizer, [*LOOKUP, ToolMessage(FOUND)]).ids
    assert tokenizer.decode(ids).endswith("<|im_start|>assistant\n")


@needs_instruct
@pytest.mark.skipif(
    not (MODEL_DIR / "tokenizer.json").is_file(), reason=f"no tokenizer.json in {MODEL_DIR}"
)
@pytest.mark.parametrize("name", list(CONVERSATIONS))
def test_instruct_2507_prompt_is_the_default_prompt_minus_the_thinking_block(name: str) -> None:
    messages = CONVERSATIONS[name]
    thinking_off = build(PromptTokenizer.from_dir(MODEL_DIR), messages).ids
    instruct = build(PromptTokenizer.from_dir(INSTRUCT_DIR), messages).ids
    assert thinking_off[: len(instruct)] == instruct
    assert len(thinking_off) - len(instruct) == THINKING_BLOCK_TOKENS
