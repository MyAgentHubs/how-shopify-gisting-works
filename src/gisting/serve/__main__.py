import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, field
from types import FrameType
from typing import NoReturn, TextIO, TypeVar

from gisting.agent.assemble import Loaded
from gisting.agent.state import TurnResult
from gisting.prompt.messages import Message
from gisting.serve.app import AppContext, ServeServer, make_server
from gisting.serve.config import LIMITS, ConfigError, ServeEnv, load_env
from gisting.serve.contract import Mode
from gisting.serve.crashes import Watch, crash_hook
from gisting.serve.failures import FailureLimits, FailureStore
from gisting.serve.gate import Gate, GateLimits
from gisting.serve.loading import LoadError, load_lookup, load_models
from gisting.serve.logs import LogRecord, RequestLog, degraded_logger
from gisting.serve.runner import LookupParts, make_runner
from gisting.serve.scope import TurnScope
from gisting.serve.service import Service
from gisting.serve.store import SessionStore, StoreLimits
from gisting.tools.policy import load_policy

T = TypeVar("T")
EXIT_OK = 0
EXIT_FAILED = 1
SIGNALS = (signal.SIGTERM, signal.SIGINT)
POLL_INTERVAL_S = 0.05
JOIN_S = 5.0

ModelsLoader = Callable[[ServeEnv], tuple[Loaded, Loaded]]
LookupLoader = Callable[[ServeEnv], LookupParts]
SignalInstaller = Callable[[Callable[[], None]], None]


def install_signals(stop: Callable[[], None]) -> None:
    def handle(_number: int, _frame: FrameType | None) -> None:
        stop()

    for number in SIGNALS:
        signal.signal(number, handle)


@dataclass(frozen=True)
class Hooks:
    environ: Mapping[str, str] = field(repr=False)
    stream: TextIO
    load_models: ModelsLoader = load_models
    load_lookup: LookupLoader = load_lookup
    install_signals: SignalInstaller = install_signals


class TurnNotReady(Exception):
    pass


class StartupFailure(Exception):
    def __init__(self, stage: str, cause: BaseException) -> None:
        super().__init__(stage)
        self.stage = stage
        self.cause = cause


def staged(stage: str, build: Callable[[], T]) -> T:
    try:
        return build()
    except BaseException as error:  # noqa: BLE001
        raise StartupFailure(stage, error) from None


def failure_record(failure: StartupFailure) -> LogRecord:
    cause = failure.cause
    return LogRecord(
        "startup_failed",
        stage=failure.stage,
        error_type=type(cause).__name__,
        inner_type=cause.inner_type if isinstance(cause, LoadError) else None,
        variables=(cause.variables or None) if isinstance(cause, ConfigError) else None,
    )


def unready_turn(
    mode: Mode,
    session_id: str,
    history: list[Message],
    scope: TurnScope,
) -> TurnResult:
    raise TurnNotReady


def build_service(logs: RequestLog) -> Service:
    policy = load_policy()
    failure_limits = FailureLimits.from_limits(LIMITS, policy.failure_limit)
    return Service(
        unready_turn,
        SessionStore(StoreLimits.from_limits(LIMITS), time.monotonic),
        FailureStore(failure_limits, time.monotonic, degraded_logger(logs)),
        Gate(GateLimits.from_limits(LIMITS)),
        threading.Event(),
        LIMITS.retry_after_s,
    )


@dataclass(frozen=True)
class Listener:
    server: ServeServer
    thread: threading.Thread

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(JOIN_S)


def listen(env: ServeEnv, service: Service, logs: RequestLog) -> Listener:
    context = AppContext(service, logs, env.upstream_secret.encode("latin-1"), LIMITS)
    server = make_server(env.port, context)
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": POLL_INTERVAL_S},
        name="serve-listener",
        daemon=True,
    )
    thread.start()
    return Listener(server, thread)


@dataclass
class Loading:
    failure: StartupFailure | None = None


def load_in_background(
    hooks: Hooks, env: ServeEnv, service: Service, stop: threading.Event
) -> Loading:
    loading = Loading()

    def work() -> None:
        try:
            gist, full = staged("models", lambda: hooks.load_models(env))
            parts = staged("lookup", lambda: hooks.load_lookup(env))
            service.turn = staged("runner", lambda: make_runner(gist, full, parts))
        except StartupFailure as failure:
            loading.failure = failure
            stop.set()
        else:
            service.ready.set()

    threading.Thread(target=work, name="serve-loader", daemon=True).start()
    return loading


def run(hooks: Hooks, logs: RequestLog, resources: ExitStack, watch: Watch) -> None:
    env = staged("env", lambda: load_env(hooks.environ))
    service = staged("assemble", lambda: build_service(logs))
    resources.callback(service.gate.close)
    listener = staged("bind", lambda: listen(env, service, logs))
    resources.callback(listener.close)
    hooks.install_signals(watch.stop.set)
    loading = load_in_background(hooks, env, service, watch.stop)
    watch.stop.wait()
    if loading.failure is not None:
        raise loading.failure


def main(hooks: Hooks | None = None) -> int:
    active = hooks or Hooks(os.environ, sys.stderr)
    logs = RequestLog(active.stream)
    watch = Watch()
    previous = threading.excepthook
    threading.excepthook = crash_hook(logs, watch)
    try:
        with ExitStack() as resources:
            run(active, logs, resources, watch)
    except StartupFailure as failure:
        logs.emit(failure_record(failure))
        return EXIT_FAILED
    finally:
        threading.excepthook = previous
    return EXIT_FAILED if watch.crashed.is_set() else EXIT_OK


def exit_process(code: int) -> NoReturn:
    os._exit(code)


if __name__ == "__main__":
    exit_process(main())
