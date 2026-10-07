import importlib
from typing import Any, cast

from tokenizers import AddedToken, Tokenizer

from gisting.prompt import tokenizer as tok
from gisting.prompt.tokenizer import PromptTokenizer

models: Any = importlib.import_module("tokenizers.models")
pre_tokenizers: Any = importlib.import_module("tokenizers.pre_tokenizers")
decoders: Any = importlib.import_module("tokenizers.decoders")
trainers: Any = importlib.import_module("tokenizers.trainers")
SPECIAL = (tok.IM_START, tok.IM_END, "<|endoftext|>", "<|vision_pad|>")
PLAIN_ADDED = (
    tok.TOOL_CALL,
    tok.TOOL_CALL_END,
    tok.TOOL_RESPONSE,
    tok.TOOL_RESPONSE_END,
    tok.THINK,
    tok.THINK_END,
    "<|fim_prefix|>",
)
CORPUS = [
    "You are the customer-service assistant of Gisting Lab Store. order email tool call",
    "Where is my order #1042? My email is someone@example.com. status found shipped",
    '{"name": "lookup_order", "arguments": {"order_number": "#1042", "email": "a@b.c"}}',
    "tools function parameters properties required system user assistant 0123456789",
]


def build_tokenizer() -> Tokenizer:
    tokenizer: Any = Tokenizer(models.BPE())
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=600,
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        show_progress=False,
    )
    tokenizer.train_from_iterator(CORPUS, trainer)
    tokenizer.add_special_tokens([AddedToken(text, special=True) for text in SPECIAL])
    tokenizer.add_tokens([AddedToken(text, special=False) for text in PLAIN_ADDED])
    return cast(Tokenizer, tokenizer)


def added_ids(tokenizer: Tokenizer) -> dict[str, int]:
    return {
        token.content: token_id for token_id, token in tokenizer.get_added_tokens_decoder().items()
    }


def synthetic_prompt_tokenizer() -> PromptTokenizer:
    return PromptTokenizer(build_tokenizer())
