import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from gisting.shopify.cli_transport import CliTransport
from gisting.shopify.results import Cause, GraphQLError, NotExecuted, Ok, Result, Uncertain
from gisting.shopify.target import API_VERSION, DEV_STORE, StoreNotAllowed
from gisting.shopify.transport import Request

REQUEST = Request("order_state", "query { shop { name } }", {"query": "name:#1002"})


class Recorder:
    def __init__(self, payload: str | None, returncode: int = 0, stderr: str = "") -> None:
        self.payload = payload
        self.returncode = returncode
        self.stderr = stderr
        self.argv: list[list[str]] = []

    def __call__(self, argv: Sequence[str], timeout: float) -> "subprocess.CompletedProcess[str]":
        self.argv.append(list(argv))
        if self.payload is not None:
            output = Path(argv[argv.index("--output-file") + 1])
            output.write_text(self.payload, encoding="utf-8")
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


def run(recorder: Recorder) -> Result:
    return CliTransport(Path("app"), runner=recorder).execute(REQUEST)


def test_data_file_maps_to_ok() -> None:
    assert run(Recorder(json.dumps({"shop": {"name": "x"}}))) == Ok({"shop": {"name": "x"}})


def test_wrapped_data_file_maps_to_ok() -> None:
    assert run(Recorder(json.dumps({"data": {"a": 1}}))) == Ok({"a": 1})


def test_errors_in_file_map_to_graphql_error() -> None:
    result = run(Recorder(json.dumps({"errors": [{"message": "denied"}]})))
    assert result == GraphQLError(({"message": "denied"},))


def test_timeout_is_uncertain() -> None:
    def runner(argv: Sequence[str], timeout: float) -> "subprocess.CompletedProcess[str]":
        raise subprocess.TimeoutExpired(list(argv), timeout)

    result = CliTransport(Path("app"), runner=runner).execute(REQUEST)
    assert isinstance(result, Uncertain)


def test_tls_disconnect_without_output_is_uncertain() -> None:
    result = run(Recorder(None, 1, "│ Client network socket disconnected before secure TLS │"))
    assert isinstance(result, Uncertain)
    assert "TLS" in result.reason
    assert "│" not in result.reason


def test_shopify_cli_graphql_failure_exits_zero_without_output_file() -> None:
    result = run(Recorder(None, 0, "GraphQL operation failed."))
    assert isinstance(result, Uncertain)


def test_unreadable_output_file_is_uncertain() -> None:
    assert isinstance(run(Recorder("{not json")), Uncertain)


def test_non_object_output_file_is_uncertain() -> None:
    assert isinstance(run(Recorder("[1, 2]")), Uncertain)


def test_missing_cli_binary_is_not_executed() -> None:
    def runner(argv: Sequence[str], timeout: float) -> "subprocess.CompletedProcess[str]":
        raise FileNotFoundError("shopify")

    result = CliTransport(Path("app"), runner=runner).execute(REQUEST)
    assert result == NotExecuted(Cause.CLI_UNAVAILABLE, "shopify")


def test_command_targets_dev_store_and_api_version() -> None:
    recorder = Recorder(json.dumps({}))
    run(recorder)
    argv = recorder.argv[0]
    assert argv[argv.index("--store") + 1] == DEV_STORE
    assert argv[argv.index("--version") + 1] == API_VERSION


def test_uncertain_result_is_not_retried_by_transport() -> None:
    recorder = Recorder(None, 1)
    run(recorder)
    assert len(recorder.argv) == 1


def test_other_store_is_rejected() -> None:
    with pytest.raises(StoreNotAllowed):
        CliTransport(Path("app"), store="other.myshopify.com")
