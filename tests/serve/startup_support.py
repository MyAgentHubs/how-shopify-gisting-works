import http.client
import io
import json
import socket
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from fakes.model import FakeModel
from fakes.shopify import FakeTransport
from fakes.tokenizer import synthetic_prompt_tokenizer
from loading_support import environ_in
from runner_support import demo_order
from runner_support import lookup_parts as plain_parts

from gisting.agent.assemble import Loaded
from gisting.model_server.interface import Generation, Model
from gisting.serve.__main__ import Hooks, main
from gisting.serve.config import ServeEnv
from gisting.serve.runner import LookupParts

PATIENCE = 20.0
GIST_COUNT = 16
UPSTREAM_SECRET_VARIABLE = "GISTING_UPSTREAM_SECRET"
SECRET_HEADER = "x-gisting-upstream-secret"
DIGEST_HEADER = "x-gisting-ip-digest"
JSON_TYPE = "application/json"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def serve_environ(tmp_path: Path, port: int) -> dict[str, str]:
    return {**environ_in(tmp_path), "GISTING_SERVE_PORT": str(port)}


def lookup_parts() -> LookupParts:
    return plain_parts(FakeTransport([demo_order()]))


def loaded_pair(gist: Model, full: Model) -> tuple[Loaded, Loaded]:
    tokenizer = synthetic_prompt_tokenizer()
    return Loaded(gist, tokenizer, GIST_COUNT, "run-1"), Loaded(full, tokenizer)


def scripted_pair() -> tuple[Loaded, Loaded]:
    return loaded_pair(FakeModel([]), FakeModel([]))


def never_models(_env: ServeEnv) -> tuple[Loaded, Loaded]:
    raise AssertionError


def never_lookup(_env: ServeEnv) -> LookupParts:
    raise AssertionError


@dataclass
class Gauge:
    active: int = 0
    peak: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class GaugedModel:
    gauge: Gauge
    backend_id: str = "gauged"

    def generate(self, ids: list[int], max_new_tokens: int) -> Generation:
        with self.gauge.lock:
            self.gauge.active += 1
            self.gauge.peak = max(self.gauge.peak, self.gauge.active)
        time.sleep(0.05)
        with self.gauge.lock:
            self.gauge.active -= 1
        return Generation("Hello, how can I help?", (1, 2, 3), 1.0, 2.0, "stop")

    def count(self, text: str) -> int:
        return len(text.split())


@dataclass(frozen=True)
class Reply:
    status: int
    body: Mapping[str, object]


@dataclass
class Run:
    port: int
    stream: io.StringIO
    environ: dict[str, str]
    handlers: list[Callable[[], None]] = field(default_factory=lambda: [])
    exit_code: int | None = None
    thread: threading.Thread | None = None

    def start(
        self,
        load_models: Callable[[ServeEnv], tuple[Loaded, Loaded]],
        load_lookup: Callable[[ServeEnv], LookupParts],
    ) -> "Run":
        hooks = Hooks(self.environ, self.stream, load_models, load_lookup, self.handlers.append)
        self.thread = threading.Thread(target=self.execute, args=(hooks,), daemon=True)
        self.thread.start()
        return self

    def execute(self, hooks: Hooks) -> None:
        self.exit_code = main(hooks)

    def finish(self) -> int:
        assert self.thread is not None
        self.thread.join(PATIENCE)
        assert not self.thread.is_alive()
        assert self.exit_code is not None
        return self.exit_code

    def terminate(self) -> int:
        self.wait_for_handlers()
        self.handlers[0]()
        return self.finish()

    def wait_for_handlers(self) -> None:
        deadline = time.monotonic() + PATIENCE
        while not self.handlers and time.monotonic() < deadline:
            time.sleep(0.01)
        assert self.handlers

    def call(self, method: str, path: str, body: object = None, digest: str | None = None) -> Reply:
        headers = {SECRET_HEADER: self.environ[UPSTREAM_SECRET_VARIABLE]}
        payload = None if body is None else json.dumps(body).encode()
        if payload is not None:
            headers["content-type"] = JSON_TYPE
        if digest is not None:
            headers[DIGEST_HEADER] = digest
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=PATIENCE)
        try:
            connection.request(method, path, payload, headers)
            response = connection.getresponse()
            return Reply(response.status, cast(Mapping[str, object], json.loads(response.read())))
        finally:
            connection.close()

    def health(self) -> Reply:
        return self.call("GET", "/health")

    def generate(self, session: str, message: str, mode: str, digest: str | None = None) -> Reply:
        document = {"session_id": session, "message": message, "mode": mode}
        return self.call("POST", "/generate", document, digest)

    def wait_until_listening(self) -> None:
        deadline = time.monotonic() + PATIENCE
        while time.monotonic() < deadline:
            try:
                self.health()
            except OSError:
                time.sleep(0.01)
            else:
                return
        raise AssertionError

    def wait_until_ready(self) -> None:
        self.wait_until_listening()
        deadline = time.monotonic() + PATIENCE
        while self.health().status != 200 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert self.health().status == 200

    def records(self) -> list[dict[str, object]]:
        lines = self.stream.getvalue().splitlines()
        return [cast(dict[str, object], json.loads(line)) for line in lines]


def new_run(tmp_path: Path, drop: str | None = None) -> Run:
    port = free_port()
    environ = serve_environ(tmp_path, port)
    if drop is not None:
        del environ[drop]
    return Run(port, io.StringIO(), environ)
