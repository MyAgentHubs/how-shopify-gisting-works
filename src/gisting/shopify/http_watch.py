import http.client
import math
import socket
import threading
import urllib.request
from http.client import HTTPMessage
from types import TracebackType
from typing import IO, Self


class Watchdog:
    def __init__(self, seconds: float) -> None:
        self.fired = False
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []
        self._timer = threading.Timer(seconds, self._fire) if math.isfinite(seconds) else None
        if self._timer:
            self._timer.daemon = True

    def __enter__(self) -> Self:
        if self._timer:
            self._timer.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer.join()
        with self._lock:
            for sock in self._sockets:
                sock.close()
            self._sockets.clear()

    def _fire(self) -> None:
        with self._lock:
            self.fired = True
            for sock in self._sockets:
                cut(sock)

    def watch(self, sock: socket.socket) -> None:
        twin = sock.dup()
        with self._lock:
            if self.fired:
                cut(twin)
            self._sockets.append(twin)

    def dial(
        self,
        address: tuple[str, int],
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        sock = socket.create_connection(address, timeout, source_address)
        self.watch(sock)
        return sock


def cut(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        return


def watched_http(watch: Watchdog) -> type[http.client.HTTPConnection]:
    class Connection(http.client.HTTPConnection):
        def connect(self) -> None:
            self._create_connection = watch.dial
            super().connect()

    return Connection


def watched_https(watch: Watchdog) -> type[http.client.HTTPSConnection]:
    class Connection(http.client.HTTPSConnection):
        def connect(self) -> None:
            self._create_connection = watch.dial
            super().connect()

    return Connection


class WatchedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, watch: Watchdog) -> None:
        super().__init__()
        self._watch = watch

    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(watched_http(self._watch), req)


class WatchedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, watch: Watchdog) -> None:
        super().__init__()
        self._watch = watch

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(watched_https(self._watch), req)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def http_error_302(
        self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str, headers: HTTPMessage
    ) -> None:
        return None

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def opener_for(watch: Watchdog) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        WatchedHTTPHandler(watch), WatchedHTTPSHandler(watch), NoRedirect()
    )
