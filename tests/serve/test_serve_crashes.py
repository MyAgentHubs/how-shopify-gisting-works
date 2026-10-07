import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO

import pytest
from loading_support import CANARY
from startup_support import (
    PATIENCE,
    Run,
    free_port,
    lookup_parts,
    never_lookup,
    never_models,
    new_run,
    port_is_free,
    scripted_pair,
    serve_environ,
)

from gisting.agent.assemble import Loaded
from gisting.model_server.config import ModelConfig
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.serve.app import ServeServer
from gisting.serve.config import ServeEnv
from gisting.serve.crashes import Watch, crash_hook
from gisting.serve.gate import Gate
from gisting.serve.loading import LoadedModel, LoadError, load_models
from gisting.serve.logs import RequestLog
from gisting.serve.runner import LookupParts

ROOT = Path(__file__).resolve().parents[2]
REPEATS = 6


class Escaping(BaseException):
    pass


def boom_with_canary(*_args: object, **_kwargs: object) -> None:
    message = f"{CANARY} private"
    raise Escaping(message)


def started(
    tmp_path: Path,
    models: Callable[[ServeEnv], tuple[Loaded, Loaded]],
    lookup: Callable[[ServeEnv], LookupParts] | None = None,
) -> Run:
    return new_run(tmp_path).start(models, lookup or (lambda _env: lookup_parts()))


@pytest.mark.parametrize("raised", [Escaping, SystemExit, KeyboardInterrupt, GeneratorExit])
def test_a_loader_that_raises_any_base_exception_fails_the_startup(
    tmp_path: Path, raised: type[BaseException], capfd: pytest.CaptureFixture[str]
) -> None:
    def models(env: ServeEnv) -> tuple[Loaded, Loaded]:
        message = f"{CANARY} {env.upstream_secret}"
        raise raised(message)

    run = started(tmp_path, models)
    assert run.finish() == 1
    (record,) = run.records()
    assert (record["event"], record["stage"], record["error_type"]) == (
        "startup_failed",
        "models",
        raised.__name__,
    )
    assert CANARY not in run.stream.getvalue()
    assert CANARY not in capfd.readouterr().err
    assert port_is_free(run.port)


def test_a_lookup_loader_that_raises_a_base_exception_fails_the_startup(tmp_path: Path) -> None:
    def lookup(_env: ServeEnv) -> LookupParts:
        raise Escaping(CANARY)

    run = started(tmp_path, lambda _env: scripted_pair(), lookup)
    assert run.finish() == 1
    (record,) = run.records()
    assert (record["stage"], record["error_type"]) == ("lookup", "Escaping")


def test_the_loader_error_keeps_the_inner_type_as_a_field(tmp_path: Path) -> None:
    def load(_config: ModelConfig) -> tuple[LoadedModel, PromptTokenizer]:
        raise OSError(CANARY)

    def models(env: ServeEnv) -> tuple[Loaded, Loaded]:
        return load_models(env, load)

    run = started(tmp_path, models)
    assert run.finish() == 1
    (record,) = run.records()
    assert (record["error_type"], record["inner_type"]) == ("LoadError", "OSError")
    assert CANARY not in run.stream.getvalue()


def test_a_load_error_carries_the_inner_type_without_parsing_its_message() -> None:
    error = LoadError("model load failed: OSError", "OSError")
    assert error.inner_type == "OSError"
    assert LoadError("the model loaded without its gist artifact").inner_type is None


def test_a_crashed_listener_stops_the_process_and_logs_only_the_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ServeServer, "service_actions", boom_with_canary)
    run = started(tmp_path, lambda _env: scripted_pair())
    assert run.finish() == 1
    (record,) = [r for r in run.records() if r["event"] == "thread_crashed"]
    assert (record["thread"], record["error_type"]) == ("serve-listener", "Escaping")
    assert CANARY not in run.stream.getvalue()
    assert CANARY not in capfd.readouterr().err
    assert port_is_free(run.port)


def test_a_crashed_gate_worker_stops_the_process_and_logs_only_the_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Gate, "_take", boom_with_canary)
    run = started(tmp_path, lambda _env: scripted_pair())
    assert run.finish() == 1
    (record,) = [r for r in run.records() if r["event"] == "thread_crashed"]
    assert (record["thread"], record["error_type"]) == ("serve-gate", "Escaping")
    assert CANARY not in run.stream.getvalue()
    assert CANARY not in capfd.readouterr().err


def test_the_hook_logs_an_unwatched_thread_without_stopping_anything(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    stream, watch = io.StringIO(), Watch()
    monkeypatch.setattr(threading, "excepthook", crash_hook(RequestLog(stream), watch))
    worker = threading.Thread(target=boom_with_canary, name="side-job")
    worker.start()
    worker.join()
    (record,) = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert (record["event"], record["thread"], record["error_type"]) == (
        "thread_crashed",
        "side-job",
        "Escaping",
    )
    assert set(record) == {"ts", "event", "thread", "error_type", "where"}
    assert not watch.stop.is_set()
    assert not watch.crashed.is_set()
    assert CANARY not in stream.getvalue() + capfd.readouterr().err


def test_the_hook_is_removed_when_the_process_function_returns(tmp_path: Path) -> None:
    before = threading.excepthook
    run = new_run(tmp_path, drop="GISTING_MODEL_DIR").start(never_models, never_lookup)
    assert run.finish() == 1
    assert threading.excepthook is before


def spawn(
    tmp_path: Path, mode: str, stderr: IO[str], mark: Path
) -> tuple[subprocess.Popen[str], int]:
    port = free_port()
    tmp_path.mkdir(exist_ok=True)
    environ = {
        **serve_environ(tmp_path, port),
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests")]),
        "PATH": os.environ["PATH"],
        "CRASH_MODE": mode,
        "CRASH_MARK": str(mark),
    }
    script = str(ROOT / "tests" / "serve" / "crash_process.py")
    process = subprocess.Popen([sys.executable, script], env=environ, stderr=stderr, text=True)
    return process, port


@pytest.mark.parametrize("mode", ["base", "exit"])
def test_a_real_process_whose_loader_raises_a_base_exception_exits_one_without_the_canary(
    tmp_path: Path, mode: str
) -> None:
    log = tmp_path / "stderr.log"
    with log.open("w", encoding="utf-8") as sink:
        process, port = spawn(tmp_path, mode, sink, tmp_path / "mark")
        assert process.wait(PATIENCE) == 1
    text = log.read_text(encoding="utf-8")
    assert CANARY not in text
    assert "startup_failed" in text
    assert port_is_free(port)


def exit_code_under_spam(home: Path, mark: Path, log: Path) -> int:
    with log.open("w", encoding="utf-8") as sink:
        process, _port = spawn(home, "spam", sink, mark)
        try:
            deadline = time.monotonic() + PATIENCE
            while not mark.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            time.sleep(0.05)
            process.send_signal(signal.SIGTERM)
            return process.wait(PATIENCE)
        finally:
            process.kill()
            process.wait()


def test_sigterm_during_a_stderr_heavy_load_always_exits_zero(tmp_path: Path) -> None:
    codes = [
        exit_code_under_spam(
            tmp_path / f"home-{attempt}", tmp_path / f"mark-{attempt}", tmp_path / f"{attempt}.log"
        )
        for attempt in range(REPEATS)
    ]
    assert codes == [0] * REPEATS
