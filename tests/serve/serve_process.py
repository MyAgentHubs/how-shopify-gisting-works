import os
import sys

from startup_support import lookup_parts, scripted_pair

from gisting.serve.__main__ import Hooks, exit_process, main

if __name__ == "__main__":
    exit_process(
        main(
            Hooks(os.environ, sys.stderr, lambda _env: scripted_pair(), lambda _env: lookup_parts())
        )
    )
