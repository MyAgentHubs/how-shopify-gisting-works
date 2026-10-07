import json
import re
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from gisting.shopify.jsonvalue import Json
from gisting.shopify.results import Cause, NotExecuted, Result, Uncertain, classify_payload
from gisting.shopify.target import API_VERSION, DEV_STORE, StoreNotAllowed
from gisting.shopify.transport import Request

DEFAULT_TIMEOUT_SECONDS = 120.0
TAIL_CHARS = 240
DECORATION = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[│╭╰╮╯─]")
Runner = Callable[[Sequence[str], float], "subprocess.CompletedProcess[str]"]


def run_subprocess(argv: Sequence[str], timeout: float) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def condense(text: str) -> str:
    return " ".join(DECORATION.sub(" ", text).split())[-TAIL_CHARS:]


class CliTransport:
    def __init__(
        self,
        app_path: Path,
        store: str = DEV_STORE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        runner: Runner = run_subprocess,
    ) -> None:
        if store != DEV_STORE:
            raise StoreNotAllowed(store)
        self._app_path = app_path
        self._store = store
        self._timeout = timeout
        self._runner = runner

    @property
    def store(self) -> str:
        return self._store

    def execute(self, request: Request) -> Result:
        with tempfile.TemporaryDirectory(prefix="gisting-shopify-") as scratch:
            directory = Path(scratch)
            argv = self._prepare(request, directory)
            if isinstance(argv, NotExecuted):
                return argv
            outcome = self._spawn(argv)
            if not isinstance(outcome, subprocess.CompletedProcess):
                return outcome
            return self._read_output(directory / "result.json", outcome)

    def _prepare(self, request: Request, directory: Path) -> list[str] | NotExecuted:
        query_file = directory / "query.graphql"
        variable_file = directory / "variables.json"
        try:
            query_file.write_text(request.document, encoding="utf-8")
            variable_file.write_text(json.dumps(request.variables), encoding="utf-8")
        except OSError as error:
            return NotExecuted(Cause.LOCAL_IO, str(error))
        return [
            "shopify",
            "app",
            "execute",
            "--no-color",
            "--path",
            str(self._app_path),
            "--store",
            self._store,
            "--version",
            API_VERSION,
            "--query-file",
            str(query_file),
            "--variable-file",
            str(variable_file),
            "--output-file",
            str(directory / "result.json"),
        ]

    def _spawn(self, argv: Sequence[str]) -> "subprocess.CompletedProcess[str] | Result":
        try:
            return self._runner(argv, self._timeout)
        except subprocess.TimeoutExpired:
            return Uncertain(f"timed out after {self._timeout:g}s")
        except OSError as error:
            return NotExecuted(Cause.CLI_UNAVAILABLE, str(error))

    def _read_output(self, output: Path, outcome: "subprocess.CompletedProcess[str]") -> Result:
        tail = condense(outcome.stdout + " " + outcome.stderr)
        if not output.is_file():
            return Uncertain(f"exit {outcome.returncode}, no output file: {tail}")
        try:
            payload: Json = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            return Uncertain(f"unreadable output file: {error}")
        return classify_payload(payload)
