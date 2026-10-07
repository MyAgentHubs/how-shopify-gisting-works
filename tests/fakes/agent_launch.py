import contextlib
import io
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from fakes.tokenizer import synthetic_prompt_tokenizer

from gisting.agent.cli import Runtime, main
from gisting.eval.runner import Launched, Launcher
from gisting.model_server.interface import Generation
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.shopify.jsonvalue import JsonObject
from gisting.tools.cli import Runtime as ToolsRuntime

USER_MARK = "<|im_start|>user\n"
END_MARK = "<|im_end|>"
ORDER = re.compile(r"#\d{4}")
EMAIL = re.compile(r"[a-z2-7]{10}@orders\.example\.com", re.IGNORECASE)
ASK = "Which order do you mean?"
K = 16


class RuleModel:
    backend_id = "fake-rule-model"

    def __init__(self, tokenizer: PromptTokenizer) -> None:
        self._tokenizer = tokenizer

    def generate(self, ids: list[int], max_new_tokens: int) -> Generation:
        text = self._tokenizer.decode(ids)
        last = text.rsplit(USER_MARK, 1)[-1].split(END_MARK, 1)[0]
        order, email = ORDER.search(last), EMAIL.search(last)
        if order and email:
            arguments = {"order_number": order.group(), "email": email.group()}
            body = json.dumps({"name": "lookup_order", "arguments": arguments})
            reply = f"<tool_call>\n{body}\n</tool_call>"
        else:
            reply = ASK
        return Generation(reply, (1, 2, 3), 1.0, 2.0, "stop")

    def count(self, text: str) -> int:
        return len(text.split())


def inprocess_launcher(env_file: Path) -> Launcher:
    tokenizer = synthetic_prompt_tokenizer()
    base: JsonObject = {"base_model_revision": "fake-revision"}
    gist: JsonObject = {**base, "gist": {"run_id": "run-x", "k": K}}
    full = Runtime(ToolsRuntime(), RuleModel(tokenizer), tokenizer, identity=base)
    gisted = Runtime(ToolsRuntime(), RuleModel(tokenizer), tokenizer, K, "run-x", gist)

    def launch(argv: Sequence[str], stdin: str, env: Mapping[str, str]) -> Launched:
        runtime = gisted if "gist" in argv else full
        arguments = [*argv[argv.index("run") :], "--env-file", str(env_file)]
        out, err = io.StringIO(), io.StringIO()
        saved = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(arguments, runtime)
        finally:
            sys.stdin = saved
        return Launched(tuple(out.getvalue().splitlines()), code, err.getvalue())

    return launch
