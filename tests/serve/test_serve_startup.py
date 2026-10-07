import socket
import threading
from pathlib import Path

import pytest
from loading_support import CANARY
from startup_support import (
    PATIENCE,
    lookup_parts,
    never_lookup,
    never_models,
    new_run,
    port_is_free,
    scripted_pair,
)

import gisting.serve.__main__ as main_module
import gisting.serve.runner as runner_module
from gisting.agent.assemble import Loaded
from gisting.agent.state import ToolRunner
from gisting.serve.config import ServeEnv
from gisting.serve.logs import RequestLog
from gisting.serve.runner import LookupParts
from gisting.serve.service import Service

VARIABLES = (
    "GISTING_UPSTREAM_SECRET",
    "GISTING_EMAIL_SECRET",
    "SHOPIFY_CLIENT_SECRET",
    "GISTING_MODEL_DIR",
    "GISTING_GIST_DIR",
)


def test_health_is_loading_and_chat_is_refused_until_the_models_are_in(tmp_path: Path) -> None:
    release = threading.Event()

    def slow_models(_env: ServeEnv) -> tuple[Loaded, Loaded]:
        assert release.wait(PATIENCE)
        return scripted_pair()

    run = new_run(tmp_path).start(slow_models, lambda _env: lookup_parts())
    run.wait_until_listening()
    assert run.health().status == 503
    assert run.health().body["status"] == "loading"
    refused = run.generate("session-0001", "hello", "gist")
    assert (refused.status, refused.body["error"]) == (
        503,
        {"retry_after_s": 5, "type": "not_ready"},
    )
    release.set()
    run.wait_until_ready()
    assert run.health().body["status"] == "ready"
    assert run.terminate() == 0


@pytest.mark.parametrize("stage", ["models", "lookup"])
def test_a_failing_loader_logs_type_and_stage_only_and_frees_the_port(
    tmp_path: Path, stage: str
) -> None:
    def failing_models(env: ServeEnv) -> tuple[Loaded, Loaded]:
        if stage == "models":
            message = f"{CANARY} {env.model_dir} {env.upstream_secret}"
            raise RuntimeError(message)
        return scripted_pair()

    def failing_lookup(env: ServeEnv) -> LookupParts:
        message = f"{CANARY} {env.shopify_secret} {env.email_secret}"
        raise OSError(message)

    run = new_run(tmp_path).start(failing_models, failing_lookup)
    assert run.finish() == 1
    output = run.stream.getvalue()
    assert CANARY not in output
    assert run.environ["GISTING_UPSTREAM_SECRET"] not in output
    assert str(tmp_path) not in output
    (record,) = run.records()
    assert record["event"] == "startup_failed"
    assert record["stage"] == stage
    assert record["error_type"] == ("RuntimeError" if stage == "models" else "OSError")
    assert set(record) == {"ts", "event", "stage", "error_type"}
    assert port_is_free(run.port)


def test_a_port_already_taken_fails_at_the_bind_stage(tmp_path: Path) -> None:
    run = new_run(tmp_path)
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", run.port))
        holder.listen()
        run.start(never_models, never_lookup)
        assert run.finish() == 1
    (record,) = run.records()
    assert (record["event"], record["stage"], record["error_type"]) == (
        "startup_failed",
        "bind",
        "OSError",
    )


@pytest.mark.parametrize("name", VARIABLES)
def test_a_missing_variable_binds_nothing_and_logs_only_its_name(tmp_path: Path, name: str) -> None:
    run = new_run(tmp_path, drop=name).start(never_models, never_lookup)
    assert run.finish() == 1
    assert port_is_free(run.port)
    (record,) = run.records()
    assert record["event"] == "startup_failed"
    assert record["stage"] == "env"
    assert record["error_type"] == "ConfigError"
    assert record["variables"] == [name]
    assert CANARY not in run.stream.getvalue()


def test_every_missing_variable_is_named_at_once(tmp_path: Path) -> None:
    run = new_run(tmp_path)
    run.environ.clear()
    run.start(never_models, never_lookup)
    assert run.finish() == 1
    (record,) = run.records()
    assert record["variables"] == ["GISTING_SERVE_PORT", *VARIABLES]


def test_sigterm_closes_the_server_and_exits_zero(tmp_path: Path) -> None:
    run = new_run(tmp_path).start(lambda _env: scripted_pair(), lambda _env: lookup_parts())
    run.wait_until_ready()
    assert not port_is_free(run.port)
    assert run.terminate() == 0
    assert port_is_free(run.port)
    assert run.records() == []


def test_a_signal_while_the_models_still_load_exits_zero_without_waiting(tmp_path: Path) -> None:
    release = threading.Event()
    started = threading.Event()

    def stuck(_env: ServeEnv) -> tuple[Loaded, Loaded]:
        started.set()
        release.wait(PATIENCE)
        return scripted_pair()

    run = new_run(tmp_path).start(stuck, lambda _env: lookup_parts())
    assert started.wait(PATIENCE)
    assert run.terminate() == 0
    assert port_is_free(run.port)
    release.set()


def test_a_tool_set_mismatch_fails_the_runner_stage_and_the_service_is_never_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def only_lookup(lookup: ToolRunner) -> dict[str, ToolRunner]:
        return {"lookup_order": lookup}

    services: list[Service] = []
    build = main_module.build_service

    def capturing(logs: RequestLog) -> Service:
        services.append(build(logs))
        return services[0]

    monkeypatch.setattr(runner_module, "production_tools", only_lookup)
    monkeypatch.setattr(main_module, "build_service", capturing)
    run = new_run(tmp_path).start(lambda _env: scripted_pair(), lambda _env: lookup_parts())
    assert run.finish() == 1
    (record,) = run.records()
    assert (record["event"], record["stage"], record["error_type"]) == (
        "startup_failed",
        "runner",
        "ToolSetMismatch",
    )
    assert not services[0].ready.is_set()
    assert services[0].turn is main_module.unready_turn
    assert port_is_free(run.port)
