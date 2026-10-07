import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from startup_support import lookup_parts, new_run, scripted_pair

import gisting.serve.__main__ as main_module
from gisting.agent.assemble import Loaded
from gisting.serve.config import ServeEnv
from gisting.serve.gate import Failed
from gisting.serve.logs import RequestLog
from gisting.serve.runner import TurnRunner
from gisting.serve.service import Service


class Witness(threading.Event):
    def __init__(self, probe: Callable[[], object]) -> None:
        super().__init__()
        self.probe = probe
        self.seen: list[object] = []

    def set(self) -> None:
        self.seen.append(self.probe())
        super().set()


def watch_services(monkeypatch: pytest.MonkeyPatch) -> list[Service]:
    services: list[Service] = []
    build = main_module.build_service

    def capturing(logs: RequestLog) -> Service:
        service = build(logs)
        service.ready = Witness(lambda: service.turn)
        services.append(service)
        return service

    monkeypatch.setattr(main_module, "build_service", capturing)
    return services


def test_the_real_turn_is_in_place_before_the_service_reports_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = watch_services(monkeypatch)
    run = new_run(tmp_path).start(lambda _env: scripted_pair(), lambda _env: lookup_parts())
    run.wait_until_ready()
    assert run.terminate() == 0
    service = services[0]
    assert isinstance(service.ready, Witness)
    assert len(service.ready.seen) == 1
    assert isinstance(service.ready.seen[0], TurnRunner)
    assert service.turn is service.ready.seen[0]


def test_the_gate_is_closed_when_the_process_function_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = watch_services(monkeypatch)
    run = new_run(tmp_path).start(lambda _env: scripted_pair(), lambda _env: lookup_parts())
    run.wait_until_ready()
    service = services[0]
    assert service.gate.stats().healthy
    assert run.terminate() == 0
    assert not service.gate.stats().healthy
    assert service.gate.submit(lambda _deadline: "late", lambda _value: None) == Failed(
        "WorkerStopped"
    )


def test_the_gate_is_closed_after_a_failed_startup_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = watch_services(monkeypatch)

    def failing(_env: ServeEnv) -> tuple[Loaded, Loaded]:
        raise OSError

    run = new_run(tmp_path).start(failing, lambda _env: lookup_parts())
    assert run.finish() == 1
    assert not services[0].gate.stats().healthy
