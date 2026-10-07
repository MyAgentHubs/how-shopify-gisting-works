import os
import sys
from pathlib import Path

from loading_support import CANARY
from startup_support import lookup_parts, scripted_pair

from gisting.agent.assemble import Loaded
from gisting.serve.__main__ import Hooks, exit_process, main
from gisting.serve.config import ServeEnv

LINE = "progress " + "x" * 200 + "\n"


class Escaping(BaseException):
    pass


def models(env: ServeEnv) -> tuple[Loaded, Loaded]:
    mode = os.environ["CRASH_MODE"]
    if mode == "base":
        message = f"{CANARY} {env.model_dir} {env.upstream_secret}"
        raise Escaping(message)
    if mode == "exit":
        raise SystemExit(CANARY)
    if mode == "spam":
        Path(os.environ["CRASH_MARK"]).write_text("loading", encoding="utf-8")
        while True:
            sys.stderr.write(LINE)
    return scripted_pair()


if __name__ == "__main__":
    exit_process(main(Hooks(os.environ, sys.stderr, models, lambda _env: lookup_parts())))
