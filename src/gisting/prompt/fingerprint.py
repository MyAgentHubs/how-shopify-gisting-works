import hashlib

from gisting.prompt.assemble import tools_segment
from gisting.prompt.rules import rules_text
from gisting.prompt.schema import load_tool_schemas
from gisting.prompt.tokenizer import PromptTokenizer


def rules_sha256() -> str:
    return hashlib.sha256(rules_text().encode()).hexdigest()


def tools_sha256(tokenizer: PromptTokenizer) -> str:
    ids = tools_segment(tokenizer, load_tool_schemas().values()).ids
    return hashlib.sha256(",".join(str(token_id) for token_id in ids).encode()).hexdigest()
