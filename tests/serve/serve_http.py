import http.client
import io
import json
import socket
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import cast

from serve_support import FakeTurn, make_service

from gisting.serve.app import SECRET_HEADER, AppContext, ServeServer, make_server
from gisting.serve.config import LIMITS, Limits
from gisting.serve.logs import RequestLog
from gisting.serve.service import Service
from gisting.serve.store import StoreLimits

SECRET = "upstream-secret-for-tests-0123456789"
GOOD_SESSION = "session-0001"
JSON_HEADERS = {"content-type": "application/json", SECRET_HEADER: SECRET}
READ_TIMEOUT = 10.0


@dataclass(frozen=True)
class Reply:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.body))


@dataclass(frozen=True)
class Running:
    server: ServeServer
    service: Service
    turn: FakeTurn
    log: io.StringIO

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def call(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Reply:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=READ_TIMEOUT)
        try:
            connection.request(method, path, body, headers if headers is not None else {})
            response = connection.getresponse()
            names = {name.lower(): value for name, value in response.getheaders()}
            return Reply(response.status, names, response.read())
        finally:
            connection.close()

    def generate(self, document: object, headers: dict[str, str] | None = None) -> Reply:
        body = json.dumps(document).encode()
        return self.call("POST", "/generate", body, JSON_HEADERS if headers is None else headers)

    def head(self, extra: dict[str, str], request_line: str = "POST /generate HTTP/1.1") -> bytes:
        headers = {"host": f"127.0.0.1:{self.port}", SECRET_HEADER: SECRET, **extra}
        lines = [request_line, *(f"{name}: {value}" for name, value in headers.items())]
        return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")

    def raw(self, payload: bytes, tail: bytes = b"") -> Reply:
        with socket.create_connection(("127.0.0.1", self.port), timeout=READ_TIMEOUT) as client:
            client.sendall(payload)
            if tail:
                client.sendall(tail)
            return read_reply(client)


def read_reply(client: socket.socket) -> Reply:
    data = b""
    while chunk := client.recv(65536):
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.lower()] = value.strip()
    return Reply(int(lines[0].split()[1]), headers, body)


@contextmanager
def started(
    turn: FakeTurn | None = None,
    *,
    ready: bool = True,
    limits: Limits = LIMITS,
    store_limits: StoreLimits | None = None,
) -> Generator[Running]:
    fake = turn or FakeTurn()
    service = make_service(
        fake,
        ready=ready,
        waiting=limits.max_waiting,
        total=limits.total_deadline_s,
        store_limits=store_limits,
    )
    log = io.StringIO()
    context = AppContext(service, RequestLog(log), SECRET.encode(), limits)
    server = make_server(0, context)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield Running(server, service, fake, log)
    finally:
        server.shutdown()
        server.server_close()
        service.gate.close()
        thread.join(READ_TIMEOUT)


def limited(**changes: float) -> Limits:
    return replace(LIMITS, **changes)


def quick_limits(socket_timeout_s: float = 0.5) -> Limits:
    return limited(socket_timeout_s=socket_timeout_s)
